"""The Organisation register: the shape, before any route writes to it.

Spec: docs/superpowers/specs/2026-09-22-funding-search-engine-master-design.md
section 6.1. These three tests fix the shape; the dedupe behaviour that rests on
it is tested against `record_organisation` further down.
"""

import pytest
from django.db import IntegrityError, transaction

from apps.funding.models import _HOLDER_VALUES
from apps.research.models import Organisation, OrganisationDomain, OrganisationIdentifier
from apps.research.register import record_organisation

pytestmark = pytest.mark.django_db


def _org(domain="bwstiftung.de", **kwargs):
    fields = {
        "primary_domain": domain,
        "name": "Baden-Württemberg Stiftung",
        "kind": "PRIVATE_FOUNDATION",
        "country_code": "DE",
        "found_via": ["REGISTER"],
    }
    fields.update(kwargs)
    return Organisation.objects.create(**fields)


def test_one_organisation_can_hold_several_domains():
    """ROR returns bwstiftung.de for the foundation whose scholarship lives on
    bw-stipendium.de (measured 2026-09-19). Under a one-domain key those never
    join, and the award's holder and the register's row are different objects."""
    organisation = _org()
    for domain in ("bwstiftung.de", "bw-stipendium.de"):
        OrganisationDomain.objects.create(
            organisation=organisation, registrable_domain=domain, found_via=["REGISTER"]
        )

    held = set(
        OrganisationDomain.objects.filter(organisation=organisation).values_list(
            "registrable_domain", flat=True
        )
    )
    assert held == {"bwstiftung.de", "bw-stipendium.de"}
    # And the second domain cannot be claimed by a second organisation: the
    # domain row is the key, so a collision is a merge question, never two rows.
    other = _org(domain="example-foundation.de", name="Another Foundation")
    with pytest.raises(IntegrityError), transaction.atomic():
        OrganisationDomain.objects.create(
            organisation=other, registrable_domain="bw-stipendium.de", found_via=["SEARCH"]
        )


def test_a_new_domain_attaches_only_on_a_shared_identifier_never_on_a_name():
    """The resolver measurements' lesson: adjacent organisations share names
    (Carl-Zeiss-Stiftung vs ZEISS; Inönü Vakfi vs Inönü Üniversitesi). An
    identifier (ROR, Wikidata, EACEA PIC) is evidence; a matching name is not.

    The shape that makes that possible: `(scheme, value)` is unique across the
    register, so an identifier can only ever point at one organisation -- while
    `name` and `names` carry no uniqueness at all, so nothing can be keyed on
    them by accident.
    """
    foundation = _org(domain="carl-zeiss-stiftung.de", name="Carl-Zeiss-Stiftung")
    company = _org(domain="zeiss.com", name="Carl-Zeiss-Stiftung")  # the same label
    assert foundation.pk != company.pk, "a shared name must not collapse two organisations"

    OrganisationIdentifier.objects.create(
        organisation=foundation, scheme="ROR", value="02nv7yv05"
    )
    with pytest.raises(IntegrityError), transaction.atomic():
        OrganisationIdentifier.objects.create(
            organisation=company, scheme="ROR", value="02nv7yv05"
        )


def test_kind_is_the_holder_vocabulary_not_a_second_taxonomy():
    """A funder's kind IS its holder type (spec 6.1). Two taxonomies over one
    object is how a register and a reader come to disagree about what a body is.

    INFRASTRUCTURE is deliberately absent from `kind` (decision log row 6): a
    mail or CDN host is `status=REJECTED, rejected_reason=INFRASTRUCTURE`, which
    is a fact about the host, not a kind of funder.
    """
    assert tuple(value for value, _ in Organisation.KIND_CHOICES) == _HOLDER_VALUES
    assert "INFRASTRUCTURE" not in _HOLDER_VALUES

    with pytest.raises(IntegrityError), transaction.atomic():
        _org(domain="mail.example.org", kind="INFRASTRUCTURE")

    rejected = _org(
        domain="mail.example.org",
        kind="UNSTATED",
        status="REJECTED",
        rejected_reason="INFRASTRUCTURE",
    )
    assert rejected.status == "REJECTED"


def test_a_rejected_reason_is_only_ever_set_on_a_rejected_row():
    """Otherwise a CANDIDATE carries a reason it was not rejected for, and the
    sweep's "never fetched twice" saving reads off a field that means nothing."""
    with pytest.raises(IntegrityError), transaction.atomic():
        _org(domain="live-funder.org", status="CANDIDATE", rejected_reason="NOT_A_FUNDER")


# --- record_organisation: the dedupe seam -----------------------------------
#
# Lookup order is the whole function: any domain, then any supplied identifier,
# then create. Never a name.


def test_a_domain_already_known_returns_its_organisation_and_adds_the_route_tag():
    """Discovery reaches the same body by four routes; found_via is a list so a
    per-route tally (section 15) can say which route found what, and the second
    route must not create a second row."""
    first = record_organisation(
        domain="https://www.bwstiftung.de/foerderung",
        name="Baden-Württemberg Stiftung",
        kind="PRIVATE_FOUNDATION",
        country_code="DE",
        found_via="REGISTER",
    )
    second = record_organisation(
        domain="bwstiftung.de",
        name="BW Stiftung",
        kind="PRIVATE_FOUNDATION",
        country_code="DE",
        found_via="SEARCH:exa",
    )

    assert second.pk == first.pk
    assert Organisation.objects.count() == 1
    assert second.found_via == ["REGISTER", "SEARCH:exa"]
    # The second route's label is kept, but only as a label -- it is never a key.
    assert set(second.names) == {"Baden-Württemberg Stiftung", "BW Stiftung"}
    assert second.name == "Baden-Württemberg Stiftung"
    # A URL keys on its registrable domain, not on the host it was written with.
    assert second.primary_domain == "bwstiftung.de"


def test_a_repeated_route_tag_is_not_recorded_twice():
    """A per-route tally counts organisations found by a route, not fetches. A
    weekly sweep appending REGISTER every week would make one body look like
    fifty-two."""
    for _ in range(3):
        organisation = record_organisation(
            domain="bwstiftung.de",
            name="Baden-Württemberg Stiftung",
            kind="PRIVATE_FOUNDATION",
            country_code="DE",
            found_via="REGISTER",
        )
    assert organisation.found_via == ["REGISTER"]


def test_a_second_domain_attaches_on_a_shared_identifier():
    """ROR returns bwstiftung.de for the foundation whose scholarship lives on
    bw-stipendium.de. The ROR id is what joins them; nothing else could."""
    first = record_organisation(
        domain="bwstiftung.de",
        name="Baden-Württemberg Stiftung",
        kind="PRIVATE_FOUNDATION",
        country_code="DE",
        found_via="REGISTER",
        identifiers=(("ROR", "01z8vbc42"),),
    )
    second = record_organisation(
        domain="bw-stipendium.de",
        name="Baden-Württemberg-STIPENDIUM",
        kind="PRIVATE_FOUNDATION",
        country_code="DE",
        found_via="HUB",
        identifiers=(("ROR", "01z8vbc42"),),
    )

    assert second.pk == first.pk
    assert Organisation.objects.count() == 1
    assert set(
        OrganisationDomain.objects.filter(organisation=first).values_list(
            "registrable_domain", flat=True
        )
    ) == {"bwstiftung.de", "bw-stipendium.de"}
    # The display key does not move: the first domain recorded stays the label.
    assert first.primary_domain == "bwstiftung.de"
    assert OrganisationIdentifier.objects.count() == 1


def test_a_matching_name_alone_never_merges_two_organisations():
    """Carl-Zeiss-Stiftung vs ZEISS; Inönü Vakfi vs Inönü Üniversitesi. An
    identifier is evidence. A name is a coincidence waiting to happen, and a
    merge is not reversible by the route that made it."""
    foundation = record_organisation(
        domain="carl-zeiss-stiftung.de",
        name="Carl-Zeiss-Stiftung",
        kind="PRIVATE_FOUNDATION",
        country_code="DE",
        found_via="REGISTER",
    )
    company = record_organisation(
        domain="zeiss.com",
        name="Carl-Zeiss-Stiftung",  # the identical label
        kind="EMPLOYER",
        country_code="DE",
        found_via="SEARCH:exa",
    )
    assert company.pk != foundation.pk
    assert Organisation.objects.count() == 2


def test_an_infrastructure_host_is_stored_rejected_so_it_is_never_fetched_twice():
    """mail., vpn., cdn. hosts are a fifth of an inventory sweep. Storing the
    rejection is the whole saving; forgetting it pays the fetch every cycle."""
    rejected = record_organisation(
        domain="cdn.example-university.de",
        name="cdn.example-university.de",
        kind="UNSTATED",
        country_code="",
        found_via="INVENTORY",
        status=Organisation.Status.REJECTED,
        rejected_reason=Organisation.RejectedReason.INFRASTRUCTURE,
    )
    assert rejected.status == "REJECTED"
    assert rejected.rejected_reason == "INFRASTRUCTURE"

    # And the next sweep that trips over the same host gets the refusal back
    # rather than a fresh CANDIDATE to go and fetch.
    again = record_organisation(
        domain="https://cdn.example-university.de/assets/logo.svg",
        name="cdn.example-university.de",
        kind="UNSTATED",
        country_code="",
        found_via="INVENTORY",
    )
    assert again.pk == rejected.pk
    assert again.status == "REJECTED"


def test_a_domain_with_no_registrable_form_is_refused_rather_than_keyed_on_a_guess():
    """registrable_domain returns "" for an IP address and an unknown suffix. A
    row keyed on "" merges every unkeyable host into one organisation, which is
    the silent-merge failure the Public Suffix List exists to prevent."""
    with pytest.raises(ValueError, match="registrable domain"):
        record_organisation(
            domain="http://192.0.2.10/funding",
            name="Some host",
            kind="UNSTATED",
            country_code="",
            found_via="INVENTORY",
        )
    assert Organisation.objects.count() == 0
