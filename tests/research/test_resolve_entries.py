"""A resolution becomes a CANDIDATE organisation, or a reason. Never a guess."""

from datetime import UTC, datetime, timedelta

import pytest
from django.utils import timezone

from apps.research.models import (
    Organisation,
    OrganisationIdentifier,
    RegisterEntry,
    refreshed_resolution,
)
from apps.research.register import record_organisation
from apps.research.resolve_entries import (
    CatalogWriteRefused,
    EntryMovedOn,
    RegisterSpec,
    due_entries,
    record_resolution,
    spec_for,
)
from apps.research.resolver import Resolution

pytestmark = pytest.mark.django_db
NOW = datetime(2026, 9, 25, tzinfo=UTC)
SPEC = RegisterSpec(country_code="TR", kind="PRIVATE_FOUNDATION")
FOUND = Resolution("hrantdink.org", "WIKIDATA", "", "Q1",
                   ("HRANT DİNK VAKFI", "Hrant Dink Foundation"))


def entry(key: str = "k", **overrides: object) -> RegisterEntry:
    fields: dict[str, object] = dict(
        register="vgm_tr", external_key=key, name="HRANT DİNK VAKFI",
        names=["HRANT DİNK VAKFI"], resolution=RegisterEntry.Resolution.UNRESOLVED,
        last_seen=timezone.now(),
    )
    fields.update(overrides)
    return RegisterEntry.objects.create(**fields)


def test_a_resolution_writes_a_candidate_with_every_name_and_the_wikidata_id() -> None:
    e = entry()
    record_resolution(e, FOUND, spec=SPEC, now=NOW)
    e.refresh_from_db()
    org = e.organisation
    assert org is not None
    assert (e.resolution, e.resolved_via, e.unresolved_reason) == ("RESOLVED", "WIKIDATA", "")
    # The register vouched for the body, not for the domain.
    assert org.status == Organisation.Status.CANDIDATE
    assert org.found_via == ["RESOLVER:WIKIDATA"]
    assert (org.kind, org.country_code) == ("PRIVATE_FOUNDATION", "TR")
    assert "Hrant Dink Foundation" in org.names
    assert OrganisationIdentifier.objects.get(scheme="WIKIDATA").value == "Q1"


def test_an_unresolved_name_keeps_what_it_learned_and_says_why() -> None:
    e = entry()
    record_resolution(
        e, Resolution(reason="TITLE_MISMATCH", names=("HRANT DİNK VAKFI", "Hrant Dink Foundation")),
        spec=SPEC, now=NOW,
    )
    e.refresh_from_db()
    assert (e.resolution, e.unresolved_reason, e.resolution_attempted_at) == (
        "UNRESOLVED", "TITLE_MISMATCH", NOW,
    )
    assert e.names == ["HRANT DİNK VAKFI", "Hrant Dink Foundation"]


def test_an_identifier_another_body_holds_is_a_question_not_a_merge() -> None:
    # The domain is already body A's; the Wikidata id is body B's. record_organisation
    # raises rather than guess which body the pair belongs to (register.py).
    a = record_organisation(domain="hrantdink.org", name="A", kind="PRIVATE_FOUNDATION",
                            country_code="TR", found_via="x")
    record_organisation(domain="other.org.tr", name="B", kind="PRIVATE_FOUNDATION",
                        country_code="TR", found_via="x", identifiers=(("WIKIDATA", "Q1"),))
    e = entry()
    record_resolution(e, FOUND, spec=SPEC, now=NOW)
    e.refresh_from_db()
    a.refresh_from_db()
    assert (e.resolution, e.resolved_via, e.unresolved_reason, e.organisation_id) == (
        "CONFLICT", "", "IDENTIFIER_CONFLICT", None,
    )
    assert "Hrant Dink Foundation" not in a.names  # the failed attempt rolled back
    assert a.found_via == ["x"]
    assert not a.identifiers.exists()


def test_a_conflict_is_never_due_again() -> None:
    """A person's question (item 12): re-running asks it again unchanged."""
    entry("c", resolution=RegisterEntry.Resolution.CONFLICT,
          unresolved_reason="IDENTIFIER_CONFLICT", resolution_attempted_at=NOW)
    assert not due_entries("vgm_tr", now=NOW, retry_final=True).exists()


def test_diffbot_asked_is_recorded_whatever_it_answered() -> None:
    e = entry()
    record_resolution(e, Resolution(reason="NO_CANDIDATE", names=("x",), diffbot_asked=True),
                      spec=SPEC, now=NOW)
    e.refresh_from_db()
    assert e.diffbot_asked_at == NOW


def test_a_write_that_matches_nothing_raises() -> None:
    e = entry()
    RegisterEntry.objects.filter(pk=e.pk).delete()
    with pytest.raises(CatalogWriteRefused, match="runtime_engine") as raised:
        record_resolution(e, Resolution(reason="NO_CANDIDATE", names=("x",)), spec=SPEC, now=NOW)
    assert not isinstance(raised.value, EntryMovedOn)


@pytest.mark.parametrize("bound_via", ["HUMAN", "LISTED"])
def test_a_row_bound_meanwhile_is_left_as_the_other_writer_left_it(bound_via: str) -> None:
    """A person (or a list re-read) bound the row between due_entries and the
    write: theirs is the stronger evidence, and the resolver's organisation
    write rolls back with the refusal."""
    e = entry()
    theirs = record_organisation(domain="hrant-dink.org.tr", name="HRANT DİNK VAKFI",
                                 kind="PRIVATE_FOUNDATION", country_code="TR", found_via="human")
    RegisterEntry.objects.filter(pk=e.pk).update(
        resolution="RESOLVED", resolved_via=bound_via, organisation=theirs,
    )
    with pytest.raises(EntryMovedOn, match=f"RESOLVED/{bound_via}"):
        record_resolution(e, FOUND, spec=SPEC, now=NOW)
    e.refresh_from_db()
    assert (e.resolution, e.resolved_via, e.organisation_id) == ("RESOLVED", bound_via, theirs.pk)
    assert e.resolution_attempted_at is None and e.names == ["HRANT DİNK VAKFI"]
    assert not Organisation.objects.filter(primary_domain="hrantdink.org").exists()
    assert not OrganisationIdentifier.objects.exists()


def test_a_reason_never_overwrites_a_row_that_moved_on() -> None:
    e = entry()
    RegisterEntry.objects.filter(pk=e.pk).update(resolution="CONFLICT")
    with pytest.raises(EntryMovedOn, match="CONFLICT"):
        record_resolution(e, Resolution(reason="NO_CANDIDATE", names=("x",)), spec=SPEC, now=NOW)
    e.refresh_from_db()
    assert (e.resolution, e.unresolved_reason) == ("CONFLICT", "")


def test_a_renamed_row_moved_on_too() -> None:
    """The resolver answered for the old name (vgm.record_vgm starts a renamed
    row over as never tried)."""
    e = entry()
    RegisterEntry.objects.filter(pk=e.pk).update(name="HRANT DİNK VAKFI İKTİSADİ İŞLETMESİ")
    with pytest.raises(EntryMovedOn, match="İKTİSADİ"):
        record_resolution(e, Resolution(reason="NO_CANDIDATE", names=("x",)), spec=SPEC, now=NOW)
    e.refresh_from_db()
    assert e.resolution_attempted_at is None


def test_a_row_that_moved_on_still_meters_the_diffbot_call() -> None:
    """The entity was spent; the monthly cap counts calls, not answers kept."""
    e = entry()
    RegisterEntry.objects.filter(pk=e.pk).update(resolution="CONFLICT")
    with pytest.raises(EntryMovedOn):
        record_resolution(e, Resolution(reason="NO_CANDIDATE", names=("x",), diffbot_asked=True),
                          spec=SPEC, now=NOW)
    e.refresh_from_db()
    assert (e.resolution, e.diffbot_asked_at) == ("CONFLICT", NOW)


def test_an_organisation_needs_the_country_and_kind_a_list_vouched_for() -> None:
    e = entry()
    with pytest.raises(ValueError, match="no country or kind"):
        record_resolution(e, FOUND, spec=RegisterSpec(country_code="", kind="PRIVATE_FOUNDATION"),
                          now=NOW)


def test_the_row_s_own_country_and_kind_override_the_register_s() -> None:
    spec = RegisterSpec(country_code="TR", kind="")
    assert spec_for(entry("a"), spec) == spec
    own = entry("b", country_code="AZ", kind="BANK_OR_LENDER")
    assert spec_for(own, spec) == RegisterSpec(country_code="AZ", kind="BANK_OR_LENDER")
    no_country = entry("c", kind="BANK_OR_LENDER")
    assert spec_for(no_country, RegisterSpec("", "")) == RegisterSpec("", "BANK_OR_LENDER")


def test_due_entries_skip_final_reasons_and_retry_fetch_failures_after_a_week() -> None:
    entry("never")
    entry("final", unresolved_reason="NO_CANDIDATE", resolution_attempted_at=NOW)
    entry("fresh-failure", unresolved_reason="FETCH_FAILED", resolution_attempted_at=NOW)
    entry("old-failure", unresolved_reason="FETCH_FAILED",
          resolution_attempted_at=NOW - timedelta(days=8))

    def keys(qs):
        return sorted(qs.values_list("external_key", flat=True))

    assert keys(due_entries("vgm_tr", now=NOW)) == ["never", "old-failure"]
    assert keys(due_entries("vgm_tr", now=NOW, retry_final=True)) == [
        "final", "never", "old-failure",
    ]


def test_refreshed_resolution_evidence_precedence() -> None:
    """A person's answer > the list/register's own evidence > the resolver's
    earlier binding > withdrawn (apps.research.closed_lists / vgm share this)."""
    resolver_bound = ("Old Name", RegisterEntry.Resolution.RESOLVED, "WIKIDATA")
    person_bound = ("Old Name", RegisterEntry.Resolution.RESOLVED, "HUMAN")

    # A person's answer is kept whole, even with the list's own evidence present.
    fields, kept = refreshed_resolution(person_bound, "Old Name", "example.org", "LISTED")
    assert (fields, kept) == ({}, True)

    # The list/register's own evidence outranks the resolver.
    fields, kept = refreshed_resolution(resolver_bound, "Old Name", "example.org", "LISTED")
    assert kept is False
    assert fields["resolution"] == RegisterEntry.Resolution.RESOLVED
    assert fields["resolved_via"] == "LISTED"

    # No new evidence, and the resolver already decided: its binding stands.
    fields, kept = refreshed_resolution(resolver_bound, "Old Name", "", "LISTED")
    assert (fields, kept) == ({}, False)

    # No evidence and no prior resolver decision: withdrawn.
    never_tried = ("Old Name", RegisterEntry.Resolution.UNRESOLVED, "")
    fields, kept = refreshed_resolution(never_tried, "Old Name", "", "LISTED")
    assert kept is False
    assert fields["resolution"] == RegisterEntry.Resolution.UNRESOLVED
    assert fields["organisation"] is None

    # A rename withdraws the resolver's binding even with no new evidence.
    fields, kept = refreshed_resolution(resolver_bound, "New Name", "", "LISTED")
    assert kept is False
    assert fields["resolution"] == RegisterEntry.Resolution.UNRESOLVED

    # A brand-new row (nothing stored) is withdrawn too.
    fields, kept = refreshed_resolution(None, "New Name", "", "LISTED")
    assert kept is False
    assert fields["resolution"] == RegisterEntry.Resolution.UNRESOLVED
