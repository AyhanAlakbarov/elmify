"""The verdict tables: shape, grants, the one writer and the wording (spec §8)."""

from datetime import timedelta

import pytest
from django.conf import settings
from django.db import IntegrityError
from django.utils import timezone

from apps.research.models import ProvenanceVerdict, ProvenanceVerdictChange
from apps.research.provenance import (
    BLOCKED_REASONS,
    RECOGNISED_REASONS,
    UNCONFIRMED_REASONS,
    WAITING_REASONS,
    WORDING,
    Reason,
    Verdict,
    recognition_note,
    record_verdict,
    verdict_of,
)
from tests.conftest import catalogue_tables
from tests.research.provenance_helpers import make_body

pytestmark = pytest.mark.django_db


def test_the_reason_enum_is_spec_4_1_and_partitions_into_three_verdicts() -> None:
    assert set(Reason.values) == RECOGNISED_REASONS | UNCONFIRMED_REASONS | BLOCKED_REASONS
    assert RECOGNISED_REASONS == {
        "register", "curated_list", "funder_list", "vouched_by_link", "government_zone",
    }
    assert BLOCKED_REASONS == {
        "mill_list", "accreditation_mill", "fee_to_release_award", "degree_for_payment",
    }
    assert UNCONFIRMED_REASONS == {
        "not_evaluated", "register_not_loaded", "absent_from_register", "no_domain_binding",
        "unmapped_list_row", "domain_registered_after_listing", "veto_conflict",
        "evidence_off_domain", "lookup_failed", "no_holder_body", "vouch_link_missing",
        "no_register",
    }
    assert verdict_of("register") == Verdict.RECOGNISED
    assert verdict_of("mill_list") == Verdict.BLOCKED
    assert verdict_of("lookup_failed") == Verdict.UNCONFIRMED
    assert verdict_of("no_register") == Verdict.UNCONFIRMED


def test_no_register_is_not_a_waiting_reason_and_never_reads_as_recognition() -> None:
    """A country with no shipped register waits on nothing: packs must not say
    "still being checked" for it forever (fix round 1, ruling 1)."""
    assert Reason.NO_REGISTER not in WAITING_REASONS
    assert WORDING[Reason.NO_REGISTER] == (
        "We have no official register for this country.",
        "Bu ölkə üçün rəsmi reyestrimiz yoxdur.",
    )
    assert recognition_note("no_register") == (
        "Recognition not confirmed: We have no official register for this country."
    )


def test_every_reason_has_fixed_wording_in_english_and_azerbaijani() -> None:
    assert set(WORDING) == set(Reason.values)
    for english, azerbaijani in WORDING.values():
        assert english.strip() and azerbaijani.strip()
        assert english != azerbaijani


def test_the_note_is_shown_for_unconfirmed_only() -> None:
    assert recognition_note("absent_from_register").startswith("Recognition not confirmed: ")
    assert recognition_note("register") == ""
    assert recognition_note("mill_list") == ""
    assert recognition_note("") == ""


def test_the_note_never_raises_on_a_code_the_wording_table_does_not_know() -> None:
    assert recognition_note("some_future_code") == ""


def test_no_unconfirmed_or_blocked_wording_reads_as_recognition() -> None:
    """Controller ruling: veto_conflict's old EN/AZ text opened with positive
    recognition language ("Recognised, but ..." / "Tanınır, lakin ..."), so
    `recognition_note` produced "Recognition not confirmed: Recognised,
    but ...". No UNCONFIRMED or BLOCKED code may start that way."""
    for reason in UNCONFIRMED_REASONS | BLOCKED_REASONS:
        english, azerbaijani = WORDING[reason]
        assert not english.startswith("Recognised"), reason
        assert not azerbaijani.startswith("Tanınır"), reason


def test_a_verdict_whose_reason_belongs_to_another_verdict_is_refused() -> None:
    body = make_body("tum.de")
    with pytest.raises(IntegrityError):
        ProvenanceVerdict.objects.create(
            organisation=body, domain="tum.de", verdict="RECOGNISED", reason_code="mill_list",
            checked_at=timezone.now(),
        )


def test_record_verdict_refuses_a_mismatched_pair_before_the_database() -> None:
    with pytest.raises(ValueError, match="not a RECOGNISED reason"):
        record_verdict(
            make_body("tum.de"), "tum.de", verdict="RECOGNISED", reason_code="lookup_failed",
            evidence={}, now=timezone.now(), next_check_at=None,
        )


def test_each_transition_writes_one_change_row() -> None:
    body = make_body("tum.de")
    now = timezone.now()
    record_verdict(body, "tum.de", verdict="UNCONFIRMED", reason_code="not_evaluated",
                   evidence={}, now=now, next_check_at=now)
    record_verdict(body, "tum.de", verdict="RECOGNISED", reason_code="register",
                   evidence={"source_slug": "x"}, now=now, next_check_at=None)
    # B4: "at" is equal for both rows here, so order on "old" too -- "" sorts
    # before "UNCONFIRMED", matching the transition order the test expects.
    changes = list(ProvenanceVerdictChange.objects.filter(organisation=body).order_by("at", "old"))
    assert [(c.old, c.new, c.reason_code) for c in changes] == [
        ("", "UNCONFIRMED", "not_evaluated"),
        ("UNCONFIRMED", "RECOGNISED", "register"),
    ]


def test_a_reason_only_change_writes_one_row_with_old_equal_to_new() -> None:
    """UNCONFIRMED(lookup_failed) -> UNCONFIRMED(absent_from_register): the
    verdict is unchanged but the reason is not, so it is still a change row
    (`old == new == "UNCONFIRMED"`), and only one -- ProvenanceVerdictChange
    is append-only by convention, record_verdict never updates a row."""
    body = make_body("tum.de")
    now = timezone.now()
    record_verdict(body, "tum.de", verdict="UNCONFIRMED", reason_code="lookup_failed",
                   evidence={}, now=now, next_check_at=now)
    record_verdict(body, "tum.de", verdict="UNCONFIRMED", reason_code="absent_from_register",
                   evidence={}, now=now, next_check_at=now)
    all_changes = ProvenanceVerdictChange.objects.filter(organisation=body)
    assert all_changes.count() == 2  # initial "" -> UNCONFIRMED, then the reason-only change
    reason_change = all_changes.get(reason_code="absent_from_register")
    assert reason_change.old == reason_change.new == "UNCONFIRMED"


def test_an_unchanged_verdict_writes_no_second_change_row() -> None:
    body = make_body("tum.de")
    now = timezone.now()
    for _ in range(2):
        record_verdict(body, "tum.de", verdict="RECOGNISED", reason_code="register",
                       evidence={}, now=now, next_check_at=None)
    assert ProvenanceVerdictChange.objects.filter(organisation=body).count() == 1


def test_first_bound_at_is_kept_through_a_recheck_and_a_downgrade() -> None:
    body = make_body("esmt.berlin")
    first = timezone.now() - timedelta(days=400)
    record_verdict(body, "esmt.berlin", verdict="RECOGNISED", reason_code="register",
                   evidence={}, now=first, next_check_at=None)
    record_verdict(body, "esmt.berlin", verdict="RECOGNISED", reason_code="register",
                   evidence={}, now=timezone.now(), next_check_at=None)
    record_verdict(body, "esmt.berlin", verdict="UNCONFIRMED",
                   reason_code="domain_registered_after_listing", evidence={},
                   now=timezone.now(), next_check_at=None)
    assert ProvenanceVerdict.objects.get(domain="esmt.berlin").first_bound_at == first


def test_first_bound_at_survives_an_unconfirmed_lapse() -> None:
    """RECOGNISED -> UNCONFIRMED(lookup_failed) -> RECOGNISED keeps the
    ORIGINAL date: a lapse must not reset the takeover clock."""
    body = make_body("tum.de")
    first = timezone.now() - timedelta(days=400)
    for verdict, reason, at in (
        ("RECOGNISED", "register", first),
        ("UNCONFIRMED", "lookup_failed", timezone.now()),
        ("RECOGNISED", "register", timezone.now()),
    ):
        record_verdict(body, "tum.de", verdict=verdict, reason_code=reason, evidence={},
                       now=at, next_check_at=None)
    assert ProvenanceVerdict.objects.get(domain="tum.de").first_bound_at == first


def test_each_domain_of_a_body_is_its_own_verdict_row() -> None:
    """Ruling 2: verdicts are per (body, domain). A body's second domain gets
    its own row, its own first_bound_at and its own history."""
    body = make_body("nyenrode.nl")
    old = timezone.now() - timedelta(days=30)
    record_verdict(body, "nyenrode.com", verdict="RECOGNISED", reason_code="curated_list",
                   evidence={}, now=old, next_check_at=None)
    now = timezone.now()
    record_verdict(body, "nyenrode.nl", verdict="UNCONFIRMED", reason_code="absent_from_register",
                   evidence={}, now=now, next_check_at=None)
    rows = {row.domain: row for row in ProvenanceVerdict.objects.filter(organisation=body)}
    assert {d: (r.verdict, r.first_bound_at) for d, r in rows.items()} == {
        "nyenrode.com": ("RECOGNISED", old), "nyenrode.nl": ("UNCONFIRMED", None),
    }
    assert sorted(
        ProvenanceVerdictChange.objects.filter(organisation=body).values_list("domain", "new")
    ) == [("nyenrode.com", "RECOGNISED"), ("nyenrode.nl", "UNCONFIRMED")]


def test_both_tables_are_catalogue_tables(db_cursor) -> None:
    """test_catalog_grants.py then asserts, as the roles themselves, that
    runtime_web holds nothing on them and runtime_engine holds DML."""
    tables = set(catalogue_tables(db_cursor))
    assert {"research_provenanceverdict", "research_provenanceverdictchange"} <= tables


@pytest.mark.django_db(transaction=True)
def test_the_engine_role_writes_a_verdict_and_the_web_role_cannot_read_one(
    role_connection,
) -> None:
    import psycopg

    body = make_body("tum.de")
    with role_connection("runtime_engine") as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO research_provenanceverdict (id, organisation_id, domain, verdict, "
            "reason_code, evidence, checked_at) VALUES (gen_random_uuid(), %s, 'tum.de', "
            "'UNCONFIRMED', 'not_evaluated', '{}', now())",
            [body.id],
        )
        cur.execute(
            "INSERT INTO research_provenanceverdictchange (id, organisation_id, domain, old, "
            "new, reason_code, at) VALUES (gen_random_uuid(), %s, 'tum.de', '', 'UNCONFIRMED', "
            "'not_evaluated', now())",
            [body.id],
        )
    with role_connection("runtime_web") as conn, conn.cursor() as cur:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            cur.execute("SELECT 1 FROM research_provenanceverdict")


def test_the_gate_ships_off_and_a_cycle_is_thirty_days() -> None:
    assert settings.PROVENANCE_GATE_ENFORCED is False
    assert settings.PROVENANCE_CYCLE_DAYS == 30
