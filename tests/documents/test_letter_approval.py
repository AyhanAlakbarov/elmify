from uuid import uuid4

import pytest
from django.utils import timezone

from apps.documents.approval import ApprovalBlocked
from apps.documents.letter_approval import (
    compute_letter_flags,
    find_conflicting_facts,
    find_stale_examples,
    mark_letter_ready,
)
from apps.documents.letter_schemas import ClaimKind, LetterClaim, LetterContent, LetterUnit
from apps.documents.letter_verification import LetterClaimVerdict
from apps.documents.models import DocumentDraft, VerifiedFact
from apps.documents.schemas import CVContent, EducationEntry, PersonalInformation
from apps.documents.verification import Verdict
from apps.funding.models import ApplicationPrompt, AuditEvent, Program
from apps.tenancy.context import tenant_scope
from apps.tenancy.models import Membership

pytestmark = pytest.mark.django_db


def _confirmed_fact(student, *, category=VerifiedFact.Category.EDUCATION, **payload_overrides):
    payload = {"degree": "BSc"}
    payload.update(payload_overrides)
    return VerifiedFact.objects.create(
        student=student,
        category=category,
        payload=payload,
        source_tier=VerifiedFact.SourceTier.STUDENT_STATEMENT,
        source_ref="intake-1",
        confirmed_by=student,
        confirmed_at=timezone.now(),
        created_by=student,
    )


def _unconfirmed_fact(student):
    """A real ledger row the student has not confirmed. letter_verification
    ._classify returns UNCERTAIN for a FACTUAL claim citing one."""
    return VerifiedFact.objects.create(
        student=student,
        category=VerifiedFact.Category.EDUCATION,
        payload={"degree": "BSc"},
        source_tier=VerifiedFact.SourceTier.STUDENT_STATEMENT,
        source_ref="intake-unconfirmed",
        created_by=student,
    )


def _letter_content(*, fact_id, archetype="WHY_PROGRAMME"):
    """One unit, one FACTUAL claim citing fact_id. verify_letter_claims only
    checks that the cited id resolves to a confirmed fact -- unlike the CV
    engine's payload-matching verifier, it never inspects claim/fact
    payload agreement -- so any fact_id is enough to drive the verdict:
    a real confirmed VerifiedFact's id -> SUPPORTED, an id with no matching
    row -> UNSUPPORTED (letter_verification._classify)."""
    unit_text = "I completed a BSc in Berlin."
    claim_text = "a BSc"
    span_start = unit_text.index(claim_text)
    claim = LetterClaim(
        text=claim_text,
        span_start=span_start,
        span_end=span_start + len(claim_text),
        kind=ClaimKind.FACTUAL,
        fact_id=fact_id,
    )
    return LetterContent(
        language="en",
        units=(LetterUnit(archetype=archetype, text=unit_text, claims=(claim,)),),
    )


def _draft(agency, django_user_model, name, *, content=None):
    user = django_user_model.objects.create(username=name)
    student = Membership.objects.create(
        tenant=agency, user=user, role=Membership.Role.STUDENT, active=True
    )
    facts: dict = {}
    if content is None:
        # A real, confirmed VerifiedFact backs this letter's one claim so
        # Plan A's mark_ready -> verdicts_for -> verify_letter_claims
        # classifies it SUPPORTED rather than UNSUPPORTED, and the "clean"
        # cases below actually exercise the clean path rather than
        # spuriously tripping the re-derived block.
        fact = _confirmed_fact(student)
        facts = {fact.id: fact}
        content = _letter_content(fact_id=fact.id)
    draft = DocumentDraft.objects.create(
        student=student,
        kind=DocumentDraft.Kind.MOTIVATION_LETTER,
        version=1,
        content=content.model_dump(mode="json"),
        status=DocumentDraft.Status.DRAFT,
    )
    # The content is returned too: mark_letter_ready re-derives the claim
    # verdicts it blocks on, so every call site has to hand it the same
    # content the row actually stores.
    return student, draft, content, facts


def _prompt_stub(source, *, immigration=False):
    class _Stub:
        pass

    stub = _Stub()
    stub.source = source
    stub.immigration = immigration
    return stub


def test_find_conflicting_facts_detects_differing_payload_values(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        user = django_user_model.objects.create(username="lf1")
        student = Membership.objects.create(
            tenant=agency_a, user=user, role=Membership.Role.STUDENT, active=True
        )
        fact_a = VerifiedFact.objects.create(
            student=student,
            category=VerifiedFact.Category.EDUCATION,
            payload={"grade": "1.7"},
            source_tier=VerifiedFact.SourceTier.STUDENT_STATEMENT,
            source_ref="c1",
            confirmed_by=student,
            confirmed_at=timezone.now(),
            created_by=student,
        )
        fact_b = VerifiedFact.objects.create(
            student=student,
            category=VerifiedFact.Category.EDUCATION,
            payload={"grade": "1.3"},
            source_tier=VerifiedFact.SourceTier.STUDENT_STATEMENT,
            source_ref="c2",
            confirmed_by=student,
            confirmed_at=timezone.now(),
            created_by=student,
        )
        conflicting = find_conflicting_facts({fact_a.id: fact_a, fact_b.id: fact_b})
        assert conflicting == {fact_a.id, fact_b.id}


def test_find_conflicting_facts_no_conflict_when_values_agree(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        user = django_user_model.objects.create(username="lf2")
        student = Membership.objects.create(
            tenant=agency_a, user=user, role=Membership.Role.STUDENT, active=True
        )
        fact_a = VerifiedFact.objects.create(
            student=student,
            category=VerifiedFact.Category.EDUCATION,
            payload={"grade": "1.7"},
            source_tier=VerifiedFact.SourceTier.STUDENT_STATEMENT,
            source_ref="c1",
            confirmed_by=student,
            confirmed_at=timezone.now(),
            created_by=student,
        )
        assert find_conflicting_facts({fact_a.id: fact_a}) == frozenset()


def test_find_conflicting_facts_different_degrees_at_different_institutions_no_flag(
    agency_a, django_user_model
):
    """Two EDUCATION facts about two genuinely different degrees must not be
    flagged just because they happen to share payload keys."""
    with tenant_scope(agency_a.id):
        user = django_user_model.objects.create(username="lf3")
        student = Membership.objects.create(
            tenant=agency_a, user=user, role=Membership.Role.STUDENT, active=True
        )
        fact_a = VerifiedFact.objects.create(
            student=student,
            category=VerifiedFact.Category.EDUCATION,
            payload={"institution_original": "Example U", "degree_as_awarded": "BSc"},
            source_tier=VerifiedFact.SourceTier.STUDENT_STATEMENT,
            source_ref="c1",
            confirmed_by=student,
            confirmed_at=timezone.now(),
            created_by=student,
        )
        fact_b = VerifiedFact.objects.create(
            student=student,
            category=VerifiedFact.Category.EDUCATION,
            payload={"institution_original": "Other U", "degree_as_awarded": "MSc"},
            source_tier=VerifiedFact.SourceTier.STUDENT_STATEMENT,
            source_ref="c2",
            confirmed_by=student,
            confirmed_at=timezone.now(),
            created_by=student,
        )
        assert find_conflicting_facts({fact_a.id: fact_a, fact_b.id: fact_b}) == frozenset()


def test_find_conflicting_facts_same_degree_conflicting_dates_flagged(
    agency_a, django_user_model
):
    """The genuine-conflict counterpart: two facts about the *same* degree
    whose dates disagree must still be flagged."""
    with tenant_scope(agency_a.id):
        user = django_user_model.objects.create(username="lf4")
        student = Membership.objects.create(
            tenant=agency_a, user=user, role=Membership.Role.STUDENT, active=True
        )
        fact_a = VerifiedFact.objects.create(
            student=student,
            category=VerifiedFact.Category.EDUCATION,
            payload={
                "institution_original": "Example U",
                "degree_as_awarded": "BSc",
                "start_date": "2018-09-01",
            },
            source_tier=VerifiedFact.SourceTier.STUDENT_STATEMENT,
            source_ref="c1",
            confirmed_by=student,
            confirmed_at=timezone.now(),
            created_by=student,
        )
        fact_b = VerifiedFact.objects.create(
            student=student,
            category=VerifiedFact.Category.EDUCATION,
            payload={
                "institution_original": "Example U",
                "degree_as_awarded": "BSc",
                "start_date": "2019-09-01",
            },
            source_tier=VerifiedFact.SourceTier.STUDENT_STATEMENT,
            source_ref="c2",
            confirmed_by=student,
            confirmed_at=timezone.now(),
            created_by=student,
        )
        conflicting = find_conflicting_facts({fact_a.id: fact_a, fact_b.id: fact_b})
        assert conflicting == {fact_a.id, fact_b.id}


def test_compute_letter_flags_unresolved_prompt():
    prompt = _prompt_stub(ApplicationPrompt.Source.UNRESOLVED)
    flags = compute_letter_flags(
        prompt=prompt,
        letter_required=Program.LetterRequired.REQUIRED,
        facts={},
        binding_violation_after_retry=False,
    )
    assert any(f.reason == "prompt_unresolved" for f in flags)


def test_compute_letter_flags_letter_required_unknown():
    prompt = _prompt_stub(ApplicationPrompt.Source.VERIFIED)
    flags = compute_letter_flags(
        prompt=prompt,
        letter_required=Program.LetterRequired.UNKNOWN,
        facts={},
        binding_violation_after_retry=False,
    )
    assert any(f.reason == "letter_required_unknown" for f in flags)


def test_compute_letter_flags_example_not_recent(agency_a, django_user_model):
    """2026-09-14 amendment: a LEADERSHIP_EXAMPLE/RELATIONSHIP_COMMUNITY unit
    whose FACTUAL claims all point at facts dated more than five years ago
    is flagged for the counselor -- never blocked."""
    with tenant_scope(agency_a.id):
        user = django_user_model.objects.create(username="lf5")
        student = Membership.objects.create(
            tenant=agency_a, user=user, role=Membership.Role.STUDENT, active=True
        )
        old_year = timezone.now().year - 10
        fact = _confirmed_fact(student, end_date=f"{old_year}-06-01")
        content = _letter_content(fact_id=fact.id, archetype="LEADERSHIP_EXAMPLE")
        prompt = _prompt_stub(ApplicationPrompt.Source.VERIFIED)
        flags = compute_letter_flags(
            prompt=prompt,
            letter_required=Program.LetterRequired.REQUIRED,
            facts={fact.id: fact},
            binding_violation_after_retry=False,
            content=content,
        )
        assert any(f.reason == "example_not_recent" for f in flags)


def test_compute_letter_flags_recent_example_not_flagged(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        user = django_user_model.objects.create(username="lf6")
        student = Membership.objects.create(
            tenant=agency_a, user=user, role=Membership.Role.STUDENT, active=True
        )
        recent_year = timezone.now().year - 1
        fact = _confirmed_fact(student, end_date=f"{recent_year}-06-01")
        content = _letter_content(fact_id=fact.id, archetype="LEADERSHIP_EXAMPLE")
        prompt = _prompt_stub(ApplicationPrompt.Source.VERIFIED)
        flags = compute_letter_flags(
            prompt=prompt,
            letter_required=Program.LetterRequired.REQUIRED,
            facts={fact.id: fact},
            binding_violation_after_retry=False,
            content=content,
        )
        assert not any(f.reason == "example_not_recent" for f in flags)


def test_find_stale_examples_undated_fact_never_flags(agency_a, django_user_model):
    """Undated facts never count against the student."""
    with tenant_scope(agency_a.id):
        user = django_user_model.objects.create(username="lf7")
        student = Membership.objects.create(
            tenant=agency_a, user=user, role=Membership.Role.STUDENT, active=True
        )
        fact = _confirmed_fact(student)  # no date keys at all
        content = _letter_content(fact_id=fact.id, archetype="RELATIONSHIP_COMMUNITY")
        assert find_stale_examples(content, {fact.id: fact}) == ()


def test_mark_letter_ready_blocked_raises(agency_a, django_user_model):
    """An UNSUPPORTED claim blocks. The verdict is no longer asserted by the
    caller -- the content cites a fact_id with no matching row, and
    mark_letter_ready derives UNSUPPORTED from that itself."""
    with tenant_scope(agency_a.id):
        student, draft, content, facts = _draft(
            agency_a, django_user_model, "la1", content=_letter_content(fact_id=uuid4())
        )
        prompt = _prompt_stub(ApplicationPrompt.Source.VERIFIED)
        with pytest.raises(ApprovalBlocked):
            mark_letter_ready(
                document=draft,
                content=content,
                gate_violations=(),
                prompt=prompt,
                letter_required=Program.LetterRequired.REQUIRED,
                facts=facts,
                inputs={},
                binding_violation_after_retry=False,
                accepted_by=student,
            )


def test_mark_letter_ready_flagged_stays_draft_and_records_events(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        student, draft, content, facts = _draft(agency_a, django_user_model, "la2")
        prompt = _prompt_stub(ApplicationPrompt.Source.UNRESOLVED)
        result = mark_letter_ready(
            document=draft,
            content=content,
            gate_violations=(),
            prompt=prompt,
            letter_required=Program.LetterRequired.REQUIRED,
            facts=facts,
            inputs={},
            binding_violation_after_retry=False,
            accepted_by=student,
        )
        assert result.status == DocumentDraft.Status.DRAFT
        event = AuditEvent.objects.get(
            object_id=draft.id, event="document.letter_flag.prompt_unresolved"
        )
        # A counselor flag is a system-detected condition, not something
        # accepted_by (who could be the student themselves) did -- matching
        # the existing convention for an analogous auto-detected event
        # (prompt_resolution._create_unresolved's document.prompt_unresolved,
        # also actor=None). Attributing it to the caller would misrepresent
        # who did what in the audit trail.
        assert event.actor is None


def test_mark_letter_ready_clean_auto_approves(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        student, draft, content, facts = _draft(agency_a, django_user_model, "la3")
        prompt = _prompt_stub(ApplicationPrompt.Source.VERIFIED)
        result = mark_letter_ready(
            document=draft,
            content=content,
            gate_violations=(),
            prompt=prompt,
            letter_required=Program.LetterRequired.REQUIRED,
            facts=facts,
            inputs={},
            binding_violation_after_retry=False,
            accepted_by=student,
        )
        assert result.status == DocumentDraft.Status.APPROVED


def test_mark_letter_ready_reblocks_on_recomputed_verdict_despite_clean_caller_input(
    agency_a, django_user_model
):
    """The caller's own claim_verdicts/gate_violations say nothing is wrong,
    and no counselor flag applies -- so mark_letter_ready reaches its
    delegate-to-mark_ready path. mark_ready re-derives verdicts from the
    locked row's own stored content (Plan A's approval.py:verdicts_for),
    not from anything a caller asserts. This draft's one claim cites a
    fact_id with no matching VerifiedFact row, so that recomputation comes
    back UNSUPPORTED and mark_ready blocks -- proving a caller cannot wave
    a letter through by simply passing empty claim_verdicts/gate_violations.
    """
    with tenant_scope(agency_a.id):
        student, draft, content, facts = _draft(
            agency_a, django_user_model, "la4", content=_letter_content(fact_id=uuid4())
        )
        prompt = _prompt_stub(ApplicationPrompt.Source.VERIFIED)
        with pytest.raises(ApprovalBlocked):
            mark_letter_ready(
                document=draft,
                content=content,
                gate_violations=(),
                prompt=prompt,
                letter_required=Program.LetterRequired.REQUIRED,
                facts=facts,
                inputs={},
                binding_violation_after_retry=False,
                accepted_by=student,
            )
        draft.refresh_from_db()
        assert draft.status == DocumentDraft.Status.DRAFT


def test_mark_letter_ready_malformed_content_fails_closed(agency_a, django_user_model):
    """A MOTIVATION_LETTER-kind draft whose stored content is CVContent-
    shaped (not LetterContent-shaped) fails LetterContent validation inside
    verdicts_for and must raise ApprovalBlocked, not leak a raw
    pydantic.ValidationError."""
    with tenant_scope(agency_a.id):
        cv_content = CVContent(
            personal_information=PersonalInformation(
                full_name="Jane Doe", email="jane@example.com"
            ),
            education=(
                EducationEntry(
                    degree_as_awarded="BSc",
                    institution_original="Example U",
                    city="Berlin",
                    country="DE",
                    start_date="2020-09-01",
                ),
            ),
            experience=(),
            research=(),
            publications=(),
            awards=(),
            skills=(),
            languages=(),
            document_language="en",
        )
        student, draft, _content, _facts = _draft(
            agency_a, django_user_model, "la5", content=cv_content
        )
        prompt = _prompt_stub(ApplicationPrompt.Source.VERIFIED)
        # A claimless-but-valid LetterContent argument, so this function's own
        # re-derived verdicts are empty and the refusal can only come from
        # mark_ready -> verdicts_for choking on the CV-shaped STORED row.
        caller_content = LetterContent(
            language="en",
            units=(LetterUnit(archetype="WHY_PROGRAMME", text="I studied in Berlin."),),
        )
        with pytest.raises(ApprovalBlocked):
            mark_letter_ready(
                document=draft,
                content=caller_content,
                gate_violations=(),
                prompt=prompt,
                letter_required=Program.LetterRequired.REQUIRED,
                facts={},
                inputs={},
                binding_violation_after_retry=False,
                accepted_by=student,
            )
        draft.refresh_from_db()
        assert draft.status == DocumentDraft.Status.DRAFT


def _uncertain_draft(agency_a, django_user_model, name):
    user = django_user_model.objects.create(username=name)
    student = Membership.objects.create(
        tenant=agency_a, user=user, role=Membership.Role.STUDENT, active=True
    )
    fact = _unconfirmed_fact(student)
    content = _letter_content(fact_id=fact.id)
    draft = DocumentDraft.objects.create(
        student=student,
        kind=DocumentDraft.Kind.MOTIVATION_LETTER,
        version=1,
        content=content.model_dump(mode="json"),
        status=DocumentDraft.Status.DRAFT,
    )
    return student, draft, content, {fact.id: fact}


def test_mark_letter_ready_blocks_immigration_uncertain_no_caller_can_waive_it(
    agency_a, django_user_model
):
    """This plan's one non-negotiable rule: an immigration letter carrying an
    UNCERTAIN claim is blocked, with no override.

    mark_letter_ready used to take the claim verdicts from its caller, so a
    caller handing it an empty tuple waived this rule outright -- and nothing
    downstream re-derived it: approval.verdicts_for hardcodes
    immigration=False and approval._BLOCKING_VERDICTS does not contain
    UNCERTAIN at all, so Plan A's mark_ready would have approved this draft.
    No verdict tuple is passed here at all; the block has to come from
    mark_letter_ready re-deriving the verdicts itself from content + ledger,
    with this prompt's real immigration flag.
    """
    with tenant_scope(agency_a.id):
        student, draft, content, facts = _uncertain_draft(agency_a, django_user_model, "la6")
        prompt = _prompt_stub(ApplicationPrompt.Source.VERIFIED, immigration=True)
        with pytest.raises(ApprovalBlocked):
            mark_letter_ready(
                document=draft,
                content=content,
                gate_violations=(),
                prompt=prompt,
                letter_required=Program.LetterRequired.REQUIRED,
                facts=facts,
                inputs={},
                binding_violation_after_retry=False,
                accepted_by=student,
            )
        draft.refresh_from_db()
        assert draft.status == DocumentDraft.Status.DRAFT


def test_mark_letter_ready_approves_the_same_uncertain_claim_when_not_immigration(
    agency_a, django_user_model
):
    """The control for the test above, and the proof that nothing downstream
    was ever catching it: the identical UNCERTAIN claim on a non-immigration
    prompt approves. UNCERTAIN blocks only because the prompt says
    immigration, and only mark_letter_ready knows that."""
    with tenant_scope(agency_a.id):
        student, draft, content, facts = _uncertain_draft(agency_a, django_user_model, "la7")
        prompt = _prompt_stub(ApplicationPrompt.Source.VERIFIED, immigration=False)
        result = mark_letter_ready(
            document=draft,
            content=content,
            gate_violations=(),
            prompt=prompt,
            letter_required=Program.LetterRequired.REQUIRED,
            facts=facts,
            inputs={},
            binding_violation_after_retry=False,
            accepted_by=student,
        )
        assert result.status == DocumentDraft.Status.APPROVED


def test_an_uncertain_sourced_claim_raises_source_unverified():
    verdicts = (
        LetterClaimVerdict(
            "WHY_PROGRAMME", "the robotics lab", Verdict.UNCERTAIN, ClaimKind.SOURCED
        ),
    )
    flags = compute_letter_flags(
        prompt=_prompt_stub(ApplicationPrompt.Source.VERIFIED),
        letter_required=Program.LetterRequired.REQUIRED,
        facts={}, binding_violation_after_retry=False, claim_verdicts=verdicts,
    )
    assert any(f.reason == "source_unverified" and "the robotics lab" in f.detail for f in flags)


def test_a_stale_source_raises_source_stale():
    stale = (uuid4(),)
    flags = compute_letter_flags(
        prompt=_prompt_stub(ApplicationPrompt.Source.VERIFIED),
        letter_required=Program.LetterRequired.REQUIRED,
        facts={}, binding_violation_after_retry=False, stale_inputs=stale,
    )
    assert any(f.reason == "source_stale" and str(stale[0]) in f.detail for f in flags)


def test_mark_letter_ready_records_source_stale_from_the_recheck(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        student, draft, content, facts = _draft(agency_a, django_user_model, "stale")
        mark_letter_ready(
            document=draft, content=content, gate_violations=(),
            prompt=_prompt_stub(ApplicationPrompt.Source.VERIFIED),
            letter_required=Program.LetterRequired.REQUIRED,
            facts=facts, inputs={}, binding_violation_after_retry=False,
            accepted_by=student, recheck=lambda inputs: (uuid4(),),
        )
        assert AuditEvent.objects.filter(event="document.letter_flag.source_stale").exists()


def test_the_default_recheck_is_the_research_fit_one():
    import inspect

    from apps.documents.research_fit.service import recheck_research_fit

    default = inspect.signature(mark_letter_ready).parameters["recheck"].default
    assert default is recheck_research_fit
