from decimal import Decimal

import pytest

from apps.funding.models import (
    PackCandidate,
    PackVersion,
    RecommendationCandidate,
    StudentDecision,
)
from apps.funding.services import (
    PackCommandError,
    consider_named_program,
    pool_funding_gap_totals,
    reject_candidate,
    replace_candidate,
    resolve_named_program,
)
from apps.research.models import ConsultantResearchTask
from apps.tenancy.context import tenant_scope
from apps.tenancy.db import tenant_transaction
from tests.funding.conftest import make_db_candidate, make_published_pack, make_run


@pytest.fixture
def run(agency_a, membership_a):
    return make_run(agency_a, membership_a)


@pytest.fixture
def candidate_a(agency_a, run):
    return make_db_candidate(agency_a, run, program_name="MSc Chemistry", funding_gap="500.00")


@pytest.fixture
def candidate_b(agency_a, run):
    return make_db_candidate(agency_a, run, program_name="MSc Physics", funding_gap="300.00")


@pytest.fixture
def pack(agency_a, run, candidate_a, candidate_b):
    return make_published_pack(agency_a, run, (candidate_a, candidate_b))


@pytest.mark.django_db
def test_reject_creates_new_immutable_version_and_persists_state(
    agency_a, membership_a, pack, candidate_a, candidate_b
) -> None:
    with tenant_scope(agency_a.id):
        new_pack = reject_candidate(pack, candidate_a.id, membership_a)

        assert new_pack.id != pack.id
        assert new_pack.version == pack.version + 1
        # A rejected candidate is a normal student chat action (P1-8); nothing
        # else will ever publish this new version now that counselor approval
        # is gone, so reject_candidate must publish it itself or the pack is
        # stuck showing "Awaiting approval" forever.
        assert new_pack.published_at is not None
        remaining = set(
            PackCandidate.objects.filter(pack_version=new_pack).values_list(
                "candidate_id", flat=True
            )
        )
        assert remaining == {candidate_b.id}
        # the original version is untouched (immutable / append-only)
        original_pool = set(
            PackCandidate.objects.filter(pack_version=pack).values_list("candidate_id", flat=True)
        )
        assert original_pool == {candidate_a.id, candidate_b.id}

        candidate_a.refresh_from_db()
        assert candidate_a.state == RecommendationCandidate.State.REJECTED
        assert StudentDecision.objects.filter(
            candidate=candidate_a, decision=StudentDecision.Decision.REJECTED
        ).exists()


@pytest.mark.django_db
def test_rejected_candidate_is_never_recommended_again(
    agency_a, membership_a, pack, candidate_a, candidate_b
) -> None:
    with tenant_scope(agency_a.id):
        new_pack = reject_candidate(pack, candidate_a.id, membership_a)

        with pytest.raises(PackCommandError):
            replace_candidate(new_pack, candidate_b.id, candidate_a.id, membership_a)


@pytest.mark.django_db
def test_replace_only_accepts_a_reviewed_visible_candidate(
    agency_a, membership_a, run, pack, candidate_a, candidate_b
) -> None:
    checking = make_db_candidate(
        agency_a, run, program_name="Unreviewed", state=RecommendationCandidate.State.CHECKING
    )
    with tenant_scope(agency_a.id):
        with pytest.raises(PackCommandError, match="not been reviewed"):
            replace_candidate(pack, candidate_a.id, checking.id, membership_a)

        replacement = make_db_candidate(agency_a, run, program_name="MSc Biology")
        new_pack = replace_candidate(pack, candidate_a.id, replacement.id, membership_a)

        # Same as reject_candidate: nothing else will ever publish this new
        # version now that counselor approval is gone.
        assert new_pack.published_at is not None
        pool = set(
            PackCandidate.objects.filter(pack_version=new_pack).values_list(
                "candidate_id", flat=True
            )
        )
        assert pool == {candidate_b.id, replacement.id}
        candidate_a.refresh_from_db()
        assert candidate_a.state == RecommendationCandidate.State.REJECTED
        assert StudentDecision.objects.filter(
            candidate=candidate_a, decision=StudentDecision.Decision.REPLACED
        ).exists()


@pytest.mark.django_db
def test_named_program_is_checking_before_it_can_enter_pack(agency_a, membership_a, pack) -> None:
    with tenant_scope(agency_a.id):
        candidate = consider_named_program(pack, "Named Erasmus Mundus Program", membership_a)

        assert candidate.state == RecommendationCandidate.State.CHECKING
        assert not PackCandidate.objects.filter(
            pack_version=pack, candidate_id=candidate.id
        ).exists()
        assert ConsultantResearchTask.objects.filter(
            reason__icontains="Named Erasmus Mundus Program",
            state=ConsultantResearchTask.State.OPEN,
        ).exists()
        assert StudentDecision.objects.filter(
            candidate=candidate, decision=StudentDecision.Decision.CONSIDERED
        ).exists()


@pytest.mark.django_db
def test_ineligible_named_program_becomes_visible_with_reason_but_stays_out_of_pool(
    agency_a, membership_a, pack
) -> None:
    with tenant_scope(agency_a.id):
        candidate = consider_named_program(pack, "Closed Program", membership_a)

        reviewed = resolve_named_program(
            candidate,
            eligible=False,
            reason="Program is closed for the target admissions cycle.",
            source_url="https://official.example.test/closed-program",
            actor=membership_a,
        )

        assert reviewed.state == RecommendationCandidate.State.VISIBLE
        assert reviewed.eligible is False
        assert reviewed.evidence.claim == "Program is closed for the target admissions cycle."
        assert reviewed.evidence.source_url == "https://official.example.test/closed-program"
        assert not PackCandidate.objects.filter(
            pack_version=pack, candidate_id=reviewed.id
        ).exists()
        assert not ConsultantResearchTask.objects.filter(
            state=ConsultantResearchTask.State.OPEN
        ).exists()


@pytest.mark.django_db
def test_fee_total_is_recalculated_after_reject_and_replace(
    agency_a, membership_a, run, pack, candidate_a, candidate_b
) -> None:
    with tenant_scope(agency_a.id):
        assert pool_funding_gap_totals(pack) == {"EUR": Decimal("800.00")}

        after_reject = reject_candidate(pack, candidate_a.id, membership_a)
        assert pool_funding_gap_totals(after_reject) == {"EUR": Decimal("300.00")}

        replacement = make_db_candidate(
            agency_a, run, program_name="MSc Biology", funding_gap="150.00"
        )
        after_replace = replace_candidate(
            after_reject, candidate_b.id, replacement.id, membership_a
        )
        assert pool_funding_gap_totals(after_replace) == {"EUR": Decimal("150.00")}


@pytest.mark.django_db
def test_reject_is_tenant_isolated(
    agency_a, agency_b, membership_a, membership_b, pack, candidate_a
) -> None:
    with tenant_scope(agency_b.id):
        with pytest.raises(PackVersion.DoesNotExist):
            reject_candidate(pack, candidate_a.id, membership_b)


@pytest.mark.django_db
def test_reject_refuses_to_empty_the_pool(agency_a, membership_a, run) -> None:
    solo_candidate = make_db_candidate(agency_a, run, program_name="Only Option")
    solo_pack = make_published_pack(agency_a, run, (solo_candidate,))

    with tenant_scope(agency_a.id):
        with pytest.raises(PackCommandError, match="last remaining candidate"):
            reject_candidate(solo_pack, solo_candidate.id, membership_a)

        # the pool is untouched — no new version was created, nothing was rejected
        assert PackCandidate.objects.filter(pack_version=solo_pack).count() == 1
        solo_candidate.refresh_from_db()
        assert solo_candidate.state == RecommendationCandidate.State.VISIBLE


@pytest.mark.django_db
def test_named_program_funding_gap_is_a_suppressed_placeholder_not_a_fabricated_figure(
    agency_a, membership_a, pack, candidate_a, candidate_b
) -> None:
    with tenant_scope(agency_a.id):
        candidate = consider_named_program(pack, "Named Erasmus Mundus Program", membership_a)
        assert candidate.funding_gap_is_placeholder is True

        resolved = resolve_named_program(
            candidate,
            eligible=True,
            reason="Confirmed open and eligible for this cycle.",
            source_url="https://official.example.test/erasmus-mundus",
            actor=membership_a,
        )
        # resolving eligibility does not retroactively cost the candidate
        assert resolved.funding_gap_is_placeholder is True

        new_pack = replace_candidate(pack, candidate_a.id, resolved.id, membership_a)

        # the placeholder 0.00 never contributes a fabricated currency bucket
        assert pool_funding_gap_totals(new_pack) == {"EUR": Decimal("300.00")}


@pytest.mark.django_db(transaction=True)
def test_a_command_on_a_superseded_version_asks_for_a_reload(
    agency_a, membership_a, run, pack, candidate_a, candidate_b, rls_enforced_orm
) -> None:
    """A student command racing the provenance sweep: the loser holds a
    version that is no longer the latest, and writing version + 1 again would
    hit the (tenant, run, version) uniqueness constraint as a 500."""
    with tenant_scope(agency_a.id):
        with tenant_transaction(agency_a.id):
            third = make_db_candidate(agency_a, run, program_name="MSc Biology")
            spare = make_db_candidate(agency_a, run, program_name="MSc Maths")
            PackCandidate.objects.create(pack_version=pack, candidate=third)
            reject_candidate(pack, candidate_a.id, membership_a)
        with tenant_transaction(agency_a.id), pytest.raises(PackCommandError, match="reload"):
            reject_candidate(pack, candidate_b.id, membership_a)
        with tenant_transaction(agency_a.id), pytest.raises(PackCommandError, match="reload"):
            replace_candidate(pack, candidate_b.id, spare.id, membership_a)
