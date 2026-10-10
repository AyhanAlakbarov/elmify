"""The gate at the pool (spec §3, §7.1-§7.2): only programmes whose evidence
domain carries a RECOGNISED verdict and HOLDER awards whose holder domain does,
filtered in the query before the limit, behind PROVENANCE_GATE_ENFORCED."""

from uuid import uuid4

import pytest

from apps.funding.models import FundingOpportunity, Program, RecommendationCandidate
from apps.funding.pool import candidate_pool
from apps.funding.views import _pack_context
from apps.research.management.commands.run_research_worker import route
from apps.research.models import Organisation, ProvenanceVerdict
from apps.research.provenance import provenance_of_award, provenance_of_program
from apps.research.schemas import ResearchMessage
from apps.research.services import _queue_checks, handle_research_message
from apps.tenancy.context import tenant_scope
from tests.conftest import reads_no_catalogue
from tests.funding.conftest import EUR_RATES, make_db_candidate, make_published_pack, make_run
from tests.funding.test_spine import _catalogue, _message
from tests.funding.test_spine import _run as _full_run
from tests.research.provenance_helpers import (
    attach_evidence,
    evidence_program,
    make_body,
    recognise,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def gate(settings):
    settings.PROVENANCE_GATE_ENFORCED = True


def _award(body: Organisation, *, name: str = "Foundation Stipend") -> FundingOpportunity:
    return FundingOpportunity.objects.create(
        canonical_key=f"read:holder:{uuid4()}", name=name, family="PRIVATE_FOUNDATION",
        scope_type="HOLDER", holder="PRIVATE_FOUNDATION", organisation=body,
        holder_domain=body.primary_domain, agreement="AGREED", served=True,
    )


def test_only_programmes_on_a_recognised_domain_are_admitted(profile, gate) -> None:
    admitted = evidence_program("https://www.tum.de/msc")
    recognise(make_body("tum.de"), "tum.de")
    evidence_program("https://www.unknown-uni-fixture.de/msc")
    make_body("unknown-uni-fixture.de")
    evidence_program("https://www.tum.de/a", "https://blogs.tum.de/b")  # not institutional
    assert [p.id for p in candidate_pool(profile, limit=50).programs] == [admitted.id]


def test_a_fake_page_naming_tum_is_not_admissible_and_tums_own_programme_is(profile, gate) -> None:
    real = evidence_program("https://www.tum.de/msc")
    fake = evidence_program("https://tum-admissions.com/msc", institution=real.institution)
    recognise(make_body("tum.de"), "tum.de")
    make_body("tum-admissions.com")
    ids = [p.id for p in candidate_pool(profile, limit=50).programs]
    assert real.id in ids and fake.id not in ids


def test_a_joint_programme_on_a_recognised_partners_domain_is_admitted(profile, gate) -> None:
    joint = evidence_program("https://www.unibo.it/emjm", joint=True)
    recognise(make_body("unibo.it"), "unibo.it", "funder_list")
    assert [p.id for p in candidate_pool(profile, limit=50).programs] == [joint.id]


def test_a_verdict_on_another_domain_of_the_same_body_admits_nothing(profile, gate) -> None:
    """Per (body, domain): tum.de recognised says nothing about tum-online.de."""
    evidence_program("https://www.tum-online.de/msc")
    tum = make_body("tum.de")
    recognise(tum, "tum.de")
    assert candidate_pool(profile, limit=50).programs == ()


def test_the_limit_is_never_spent_on_gated_rows(profile, gate) -> None:
    for key in ("a1", "a2", "a3"):
        gated = evidence_program(f"https://www.gated-{key}-fixture.de/msc")
        Program.objects.filter(id=gated.id).update(canonical_key=key)
    admitted = evidence_program("https://www.tum.de/msc")
    Program.objects.filter(id=admitted.id).update(canonical_key="z9")
    recognise(make_body("tum.de"), "tum.de")
    assert [p.id for p in candidate_pool(profile, limit=1).programs] == [admitted.id]


def test_only_holder_awards_of_a_recognised_funder_are_admitted(profile, gate) -> None:
    good = make_body("daad.de", kind="NATIONAL_GOVERNMENT")
    recognise(good, "daad.de", "curated_list")
    shown = _award(good)
    _award(make_body("daad-scholarships.org", kind="PRIVATE_FOUNDATION"), name="Lookalike")
    assert [a.id for a in candidate_pool(profile, limit=50).awards] == [shown.id]


def test_an_award_with_no_holder_body_is_coded() -> None:
    # A saved HOLDER award cannot lack its organisation (a database
    # constraint), so the code is checked on an unsaved row (preflight B6).
    orphan = FundingOpportunity(scope_type="HOLDER", organisation=None)
    assert provenance_of_award(orphan) == (None, "no_holder_body")


def test_waiting_bodies_are_pending_and_the_empty_reason_says_so(profile, gate) -> None:
    evidence_program("https://www.tum.de/msc")
    tum = make_body("tum.de")
    result = candidate_pool(profile, limit=50)
    assert result.programs == ()
    assert result.pending_bodies == (tum.id,)
    assert result.empty_reason.startswith("1 programme or award is still being checked")
    assert "No programme" not in result.empty_reason


def test_register_not_loaded_waits_and_no_register_does_not(profile, gate) -> None:
    evidence_program("https://www.tum.de/msc")
    tum = make_body("tum.de")
    recognise(tum, "tum.de", "register_not_loaded")
    assert candidate_pool(profile, limit=50).pending_bodies == (tum.id,)
    recognise(tum, "tum.de", "no_register")
    result = candidate_pool(profile, limit=50)
    assert result.pending_bodies == ()
    assert result.empty_reason.startswith("1 matching programme or award is not shown")


def test_a_waiting_holder_award_is_pending(profile, gate) -> None:
    funder = make_body("example-funder-fixture.org", kind="PRIVATE_FOUNDATION")
    _award(funder)
    result = candidate_pool(profile, limit=50)
    assert result.awards == () and result.pending_bodies == (funder.id,)


def test_a_rejected_body_and_off_domain_evidence_are_not_pending(profile, gate) -> None:
    evidence_program("https://www.rejected-fixture.de/msc")
    rejected = make_body("rejected-fixture.de")
    Organisation.objects.filter(id=rejected.id).update(status=Organisation.Status.REJECTED)
    evidence_program("https://www.tum.de/a", "https://blogs.tum.de/b")
    make_body("tum.de")
    result = candidate_pool(profile, limit=50)
    assert result.pending_bodies == ()
    assert "still being checked" not in result.empty_reason


def test_a_rejected_body_with_a_stale_recognised_verdict_is_not_admitted(profile, gate) -> None:
    """The pool and the checker judge the same bodies: a REJECTED body is never
    checked again, so its last RECOGNISED verdict must not keep admitting it."""
    evidence_program("https://www.stale-fixture.de/msc")
    body = make_body("stale-fixture.de")
    recognise(body, "stale-fixture.de")
    Organisation.objects.filter(id=body.id).update(status=Organisation.Status.REJECTED)
    assert candidate_pool(profile, limit=50).programs == ()


def test_gated_out_matches_are_counted_not_reported_as_no_match(profile, gate) -> None:
    evidence_program("https://www.mill-fixture.de/msc")
    recognise(make_body("mill-fixture.de"), "mill-fixture.de", "accreditation_mill")
    evidence_program("https://www.unconf-fixture.de/msc")
    recognise(make_body("unconf-fixture.de"), "unconf-fixture.de", "vouch_link_missing")
    funder = make_body("blockedfunder-fixture.org", kind="PRIVATE_FOUNDATION")
    recognise(funder, "blockedfunder-fixture.org", "fee_to_release_award")
    _award(funder)
    result = candidate_pool(profile, limit=50)
    assert result.pending_bodies == ()
    assert result.empty_reason == (
        "3 matching programmes or awards are not shown because their institution's "
        "recognition is not confirmed."
    )


def test_one_gated_out_match_reads_in_the_singular(profile, gate) -> None:
    evidence_program("https://www.mill-fixture.de/msc")
    recognise(make_body("mill-fixture.de"), "mill-fixture.de", "accreditation_mill")
    assert candidate_pool(profile, limit=50).empty_reason == (
        "1 matching programme or award is not shown because its institution's "
        "recognition is not confirmed."
    )


def test_pending_wording_wins_over_gated_out_matches(profile, gate) -> None:
    evidence_program("https://www.mill-fixture.de/msc")
    recognise(make_body("mill-fixture.de"), "mill-fixture.de", "accreditation_mill")
    evidence_program("https://www.tum.de/msc")
    make_body("tum.de")
    evidence_program("https://www.lmu.de/msc")
    make_body("lmu.de")
    assert candidate_pool(profile, limit=50).empty_reason.startswith(
        "2 programmes or awards are still being checked"
    )


def test_checks_are_queued_in_batches_one_worker_can_finish_inside_the_visibility_timeout(
    agency_a, monkeypatch
) -> None:
    sent: list[ResearchMessage] = []
    monkeypatch.setattr(
        "apps.research.services.enqueue_research", lambda message, **_kw: sent.append(message)
    )
    _queue_checks(agency_a.id, uuid4(), tuple(uuid4() for _ in range(16)))
    assert [len(m.body_ids) for m in sent] == [15, 1]


def test_with_the_gate_off_the_pool_is_unchanged(profile) -> None:
    unknown = evidence_program("https://www.unknown-uni-fixture.de/msc")
    make_body("unknown-uni-fixture.de")
    result = candidate_pool(profile, limit=50)
    assert [p.id for p in result.programs] == [unknown.id] and result.pending_bodies == ()


def test_provenance_of_program() -> None:
    admitted = evidence_program("https://www.tum.de/msc")
    tum = make_body("tum.de")
    assert provenance_of_program(admitted) == (tum.id, "not_evaluated")
    recognise(tum, "tum.de")
    assert provenance_of_program(admitted) == (tum.id, "register")
    split = evidence_program("https://www.tum.de/a", "https://www.lmu.de/b")
    assert provenance_of_program(split) == (None, "evidence_off_domain")
    blog = evidence_program("https://www.tum.de/c", "https://blogs.tum.de/c")
    assert provenance_of_program(blog) == (tum.id, "evidence_off_domain")
    hosted = evidence_program("https://some-uni-fixture.netlify.app/msc")
    assert provenance_of_program(hosted) == (None, "evidence_off_domain")


def test_provenance_of_award_reads_its_holder_domain() -> None:
    funder = make_body("example-funder-fixture.org", kind="PRIVATE_FOUNDATION")
    award = _award(funder)
    assert provenance_of_award(award) == (funder.id, "not_evaluated")
    recognise(funder, "example-funder-fixture.org", "curated_list")
    assert provenance_of_award(award) == (funder.id, "curated_list")
    FundingOpportunity.objects.filter(id=award.id).update(holder_domain="")
    award.refresh_from_db()
    assert provenance_of_award(award) == (funder.id, "no_domain_binding")


@pytest.mark.django_db(transaction=True)
def test_the_pack_build_writes_codes_and_pending_bodies_and_queues_their_check(
    agency_a, membership_a, settings, monkeypatch
) -> None:
    settings.PROVENANCE_GATE_ENFORCED = True
    sent: list[ResearchMessage] = []
    monkeypatch.setattr(
        "apps.research.services.enqueue_research", lambda message, **_kw: sent.append(message)
    )
    program, award = _catalogue()
    attach_evidence(program, "https://www.tum.de/msc")
    tum = make_body("tum.de")
    recognise(tum, "tum.de")
    recognise(award.organisation, "example-foundation.org", "curated_list")
    waiting, _ = _catalogue(with_award=False, program_name="MSc Computer Science Two")
    attach_evidence(waiting, "https://www.lmu.de/msc")
    lmu = make_body("lmu.de")
    run = _full_run(agency_a, membership_a)
    with tenant_scope(agency_a.id):
        handle_research_message(_message(agency_a, run), rates=EUR_RATES)
        codes = {
            c.program_name: (c.provenance_reason_code, c.provenance_body_id)
            for c in RecommendationCandidate.objects.filter(run=run)
        }
        run.refresh_from_db()
    assert codes["MSc Computer Science"] == ("register", tum.id)
    assert codes["Foundation Stipend"] == ("curated_list", award.organisation_id)
    assert "MSc Computer Science Two" not in codes
    assert run.pending_bodies == [lmu.id]
    # Queued after the commit, for the worker -- never checked in the transaction.
    assert [(m.kind, m.run_id, m.body_ids) for m in sent] == [
        ("check_provenance", run.id, (lmu.id,))
    ]


def test_a_check_provenance_message_checks_the_pending_bodies_outside_the_run(
    agency_a, monkeypatch
) -> None:
    lmu = make_body("lmu.de")
    evidence_program("https://www.lmu.de/msc")
    tum = make_body("tum.de")
    evidence_program("https://www.tum.de/msc")
    checked: list[str] = []

    def fake_check(organisation, domain, *, now, deps):
        checked.append(domain)
        return recognise(organisation, domain)

    monkeypatch.setattr("apps.research.provenance_job.check_body", fake_check)
    monkeypatch.setattr("apps.research.management.commands.run_research_worker.Deps", dict)
    route(
        ResearchMessage(
            kind="check_provenance", tenant_id=agency_a.id, run_id=uuid4(), body_ids=(lmu.id,)
        )
    )
    assert checked == ["lmu.de"]
    assert ProvenanceVerdict.objects.get(domain="lmu.de").organisation_id == lmu.id
    assert not ProvenanceVerdict.objects.filter(organisation=tum).exists()


def test_check_provenance_needs_bodies_and_nothing_else_carries_them(agency_a) -> None:
    with pytest.raises(ValueError, match="body_ids"):
        ResearchMessage(kind="check_provenance", tenant_id=agency_a.id, run_id=uuid4())
    with pytest.raises(ValueError, match="body_ids"):
        ResearchMessage(
            kind="run_research", tenant_id=agency_a.id, run_id=uuid4(), body_ids=(uuid4(),)
        )


def test_the_gate_off_still_writes_the_codes_and_pends_nothing(
    agency_a, membership_a
) -> None:
    program, _ = _catalogue(with_award=False)
    attach_evidence(program, "https://www.tum.de/msc")
    tum = make_body("tum.de")
    run = _full_run(agency_a, membership_a)
    with tenant_scope(agency_a.id):
        handle_research_message(_message(agency_a, run), rates=EUR_RATES)
        candidate = RecommendationCandidate.objects.get(run=run)
        run.refresh_from_db()
    assert (candidate.provenance_reason_code, candidate.provenance_body_id) == (
        "not_evaluated", tum.id,
    )
    assert run.pending_bodies == []


def test_the_pack_says_how_many_are_still_being_checked_without_the_catalogue(
    agency_a, membership_a
) -> None:
    run = make_run(agency_a, membership_a)
    candidate = make_db_candidate(agency_a, run)
    make_published_pack(agency_a, run, (candidate,))
    with tenant_scope(agency_a.id):
        type(run).objects.filter(id=run.id).update(pending_bodies=[uuid4(), uuid4()])
        with reads_no_catalogue():
            context = _pack_context(membership_a)
    assert context["pending_count"] == 2
    assert context["pending_line"] == "2 institutions are still being checked."


def test_one_pending_institution_reads_in_the_singular(agency_a, membership_a) -> None:
    run = make_run(agency_a, membership_a)
    candidate = make_db_candidate(agency_a, run)
    make_published_pack(agency_a, run, (candidate,))
    with tenant_scope(agency_a.id):
        type(run).objects.filter(id=run.id).update(pending_bodies=[uuid4()])
        context = _pack_context(membership_a)
    assert context["pending_line"] == "1 institution is still being checked."
