from datetime import UTC, datetime
from uuid import uuid4

import pytest

from apps.documents.letter_schemas import ClaimKind, LetterClaim, LetterContent, LetterUnit
from apps.documents.letter_verification import verify_letter_claims
from apps.documents.models import NarrativeInput, VerifiedFact
from apps.documents.verification import Verdict
from apps.tenancy.context import tenant_scope
from apps.tenancy.models import Membership

pytestmark = pytest.mark.django_db


def _student(agency, django_user_model, name):
    user = django_user_model.objects.create(username=name)
    return Membership.objects.create(
        tenant=agency, user=user, role=Membership.Role.STUDENT, active=True
    )


def test_factual_claim_with_confirmed_fact_is_supported(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "lv1")
        fact = VerifiedFact.objects.create(
            student=student,
            category=VerifiedFact.Category.EDUCATION,
            payload={"x": 1},
            source_tier=VerifiedFact.SourceTier.STUDENT_STATEMENT,
            source_ref="c1",
            confirmed_by=student,
            confirmed_at=datetime.now(tz=UTC),
            created_by=student,
        )
        claim = LetterClaim(
            text="I completed a BSc",
            span_start=0,
            span_end=17,
            kind=ClaimKind.FACTUAL,
            fact_id=fact.id,
        )
        content = LetterContent(
            language="en",
            units=(
                LetterUnit(
                    archetype="ACADEMIC_PREPARATION", text="I completed a BSc", claims=(claim,)
                ),
            ),
        )
        verdicts = verify_letter_claims(
            content, facts={fact.id: fact}, inputs={}, immigration=False
        )
        assert verdicts[0].verdict == Verdict.SUPPORTED


def test_factual_claim_with_missing_fact_id_is_unsupported():
    claim = LetterClaim(
        text="I led a team of five",
        span_start=0,
        span_end=20,
        kind=ClaimKind.FACTUAL,
        fact_id=uuid4(),
    )
    content = LetterContent(
        language="en",
        units=(
            LetterUnit(
                archetype="LEADERSHIP_EXAMPLE", text="I led a team of five", claims=(claim,)
            ),
        ),
    )
    verdicts = verify_letter_claims(content, facts={}, inputs={}, immigration=False)
    assert verdicts[0].verdict == Verdict.UNSUPPORTED


def test_factual_claim_unconfirmed_is_uncertain_non_blocking_when_not_immigration(
    agency_a, django_user_model
):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "lv2")
        fact = VerifiedFact.objects.create(
            student=student,
            category=VerifiedFact.Category.EDUCATION,
            payload={"x": 1},
            source_tier=VerifiedFact.SourceTier.AUTHORITATIVE_DOCUMENT,
            source_ref="c2",
            confirmed_by=None,
            created_by=student,
        )
        claim = LetterClaim(
            text="claim", span_start=0, span_end=5, kind=ClaimKind.FACTUAL, fact_id=fact.id
        )
        content = LetterContent(
            language="en",
            units=(LetterUnit(archetype="ACADEMIC_PREPARATION", text="claim", claims=(claim,)),),
        )
        verdicts = verify_letter_claims(
            content, facts={fact.id: fact}, inputs={}, immigration=False
        )
        assert verdicts[0].verdict == Verdict.UNCERTAIN


def test_declared_claim_with_missing_input_id_is_unsupported():
    claim = LetterClaim(
        text="I plan to study X",
        span_start=0,
        span_end=18,
        kind=ClaimKind.DECLARED,
        input_id=uuid4(),
    )
    content = LetterContent(
        language="en",
        units=(
            LetterUnit(archetype="RESEARCH_PLAN", text="I plan to study X", claims=(claim,)),
        ),
    )
    verdicts = verify_letter_claims(content, facts={}, inputs={}, immigration=False)
    assert verdicts[0].verdict == Verdict.UNSUPPORTED


def test_declared_claim_supported_regardless_of_confirmation(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "lv3")
        entry = NarrativeInput.objects.create(
            student=student,
            kind=NarrativeInput.Kind.RESEARCH_PLAN,
            text="Study X",
            proposed_by=NarrativeInput.ProposedBy.ENGINE,
            confirmed_at=None,
        )
        claim = LetterClaim(
            text="I plan to study X",
            span_start=0,
            span_end=18,
            kind=ClaimKind.DECLARED,
            input_id=entry.id,
        )
        content = LetterContent(
            language="en",
            units=(
                LetterUnit(archetype="RESEARCH_PLAN", text="I plan to study X", claims=(claim,)),
            ),
        )
        verdicts = verify_letter_claims(
            content, facts={}, inputs={entry.id: entry}, immigration=False
        )
        assert verdicts[0].verdict == Verdict.SUPPORTED


def _research_input(entity="Chair of Robotics", url="https://www.tum.de/robotics"):
    entry = NarrativeInput(
        id=uuid4(),
        kind=NarrativeInput.Kind.RESEARCH_FIT,
        text=f"The {entity} hosts master's theses on legged locomotion.",
        proposed_by=NarrativeInput.ProposedBy.ENGINE,
        provenance={
            "sentence": f"The {entity} hosts master's theses on legged locomotion.",
            "entity": entity,
            "source_url": url,
            "page_digest": "d" * 64,
        },
    )
    return entry


def _sourced(text, *, input_id=None, url="https://www.tum.de/robotics"):
    claim = LetterClaim(
        text=text, span_start=0, span_end=len(text), kind=ClaimKind.SOURCED,
        source_url=url, input_id=input_id,
    )
    unit = LetterUnit(archetype="WHY_PROGRAMME", text=text, claims=(claim,))
    return LetterContent(language="en", units=(unit,))


def test_a_sourced_claim_without_a_producer_is_uncertain_not_supported():
    content = _sourced("the robotics lab")
    verdicts = verify_letter_claims(content, facts={}, inputs={}, immigration=False)
    assert verdicts[0].verdict == Verdict.UNCERTAIN


def test_an_engine_sourced_claim_backed_by_provenance_is_supported():
    entry = _research_input()
    content = _sourced("the Chair of Robotics works on legged locomotion", input_id=entry.id)
    verdicts = verify_letter_claims(content, facts={}, inputs={entry.id: entry}, immigration=False)
    assert verdicts[0].verdict == Verdict.SUPPORTED


def test_a_lowercase_paraphrase_of_the_entity_is_unsupported():
    entry = _research_input()
    content = _sourced("the robotics group works on legged locomotion", input_id=entry.id)
    verdicts = verify_letter_claims(content, facts={}, inputs={entry.id: entry}, immigration=False)
    assert verdicts[0].verdict == Verdict.UNSUPPORTED


def test_a_name_absent_from_the_provenance_sentence_is_unsupported():
    entry = _research_input()
    content = _sourced(
        "the Chair of Robotics, led by Anna Schmidt, works on legged locomotion",
        input_id=entry.id,
    )
    verdicts = verify_letter_claims(content, facts={}, inputs={entry.id: entry}, immigration=False)
    assert verdicts[0].verdict == Verdict.UNSUPPORTED


def test_a_fabricated_name_with_a_lowercase_joiner_is_unsupported():
    # "Institute of Advanced Study" is one capitalised-phrase run under the
    # tokenizer walk (capitalised_phrases treats "of" as a connector, not a
    # break, so it does not truncate into two separate adjacent-word runs).
    # The phrase is absent from the provenance sentence (D9's condition 2),
    # so this engine-written name must be caught as fabricated. Verified by
    # removing sourced_claim_matches' capitalised_phrases loop: the verdict
    # then flips to SUPPORTED, confirming this test exercises that check.
    entry = _research_input()
    content = _sourced(
        "the Chair of Robotics collaborates with the Institute of Advanced Study "
        "on legged locomotion",
        input_id=entry.id,
    )
    verdicts = verify_letter_claims(content, facts={}, inputs={entry.id: entry}, immigration=False)
    assert verdicts[0].verdict == Verdict.UNSUPPORTED


def test_an_invented_number_is_unsupported():
    """The audit's own example, and it verified SUPPORTED until 2026-09-24.

    A citation to a real page carrying two invented figures is worse than no
    citation: the reader can check a number faster than anything else in the
    letter, and it is the student who pays when it is wrong. Verified by
    removing the number loop from `sourced_claim_matches` -- the verdict then
    flips to SUPPORTED.
    """
    entry = _research_input()
    content = _sourced(
        "the Chair of Robotics has led the group since 1998 and supervises "
        "40 doctoral researchers",
        input_id=entry.id,
    )
    verdicts = verify_letter_claims(content, facts={}, inputs={entry.id: entry}, immigration=False)
    assert verdicts[0].verdict == Verdict.UNSUPPORTED


def test_a_number_the_page_really_states_is_supported():
    """The positive control: tightening must not block a figure that is there."""
    entry = _research_input()
    entry.provenance["sentence"] = (
        "The Chair of Robotics has hosted 12 master's theses on legged locomotion."
    )
    content = _sourced(
        "the Chair of Robotics has hosted 12 master's theses", input_id=entry.id
    )
    verdicts = verify_letter_claims(content, facts={}, inputs={entry.id: entry}, immigration=False)
    assert verdicts[0].verdict == Verdict.SUPPORTED


def test_a_number_inside_a_longer_number_does_not_satisfy_the_check():
    """Digit boundaries, not substrings: the "40" in the page's "1940" is not
    the claim's "40 doctoral researchers"."""
    entry = _research_input()
    entry.provenance["sentence"] = "The Chair of Robotics was founded in 1940."
    content = _sourced(
        "the Chair of Robotics supervises 40 doctoral researchers", input_id=entry.id
    )
    verdicts = verify_letter_claims(content, facts={}, inputs={entry.id: entry}, immigration=False)
    assert verdicts[0].verdict == Verdict.UNSUPPORTED


def test_a_different_url_from_the_provenance_is_unsupported():
    entry = _research_input()
    content = _sourced(
        "the Chair of Robotics works on legged locomotion",
        input_id=entry.id, url="https://www.tum.de/other",
    )
    verdicts = verify_letter_claims(content, facts={}, inputs={entry.id: entry}, immigration=False)
    assert verdicts[0].verdict == Verdict.UNSUPPORTED


def test_sourced_claim_citing_verified_paper_title_finding_and_year_is_supported():
    from apps.documents.letters import is_letter_blocked

    entry = _research_input(entity="Marco Hutter", url="https://rsl.ethz.ch/people/hutter")
    entry.provenance.update(
        {
            "paper_title": "Tube Model Predictive Control for Quadruped Locomotion",
            "paper_year": 2025,
            "paper_url": "https://doi.org/10.1109/tro.2025.001",
            "paper_finding": "Reduces slip on 25-degree gravel inclines by 40 percent.",
        }
    )
    content = _sourced(
        "Marco Hutter's 2025 paper on Tube Model Predictive Control reduces slip on "
        "25-degree gravel inclines by 40 percent",
        input_id=entry.id,
        url="https://rsl.ethz.ch/people/hutter",
    )
    verdicts = verify_letter_claims(content, facts={}, inputs={entry.id: entry}, immigration=False)
    assert verdicts[0].verdict == Verdict.SUPPORTED
    assert not is_letter_blocked(verdicts, (), immigration=False)

    # Also supported when citing paper_url directly:
    content_paper_url = _sourced(
        "Marco Hutter's 2025 work on Tube Model Predictive Control",
        input_id=entry.id,
        url="https://doi.org/10.1109/tro.2025.001",
    )
    verdicts_paper_url = verify_letter_claims(
        content_paper_url, facts={}, inputs={entry.id: entry}, immigration=False
    )
    assert verdicts_paper_url[0].verdict == Verdict.SUPPORTED

    # Still unsupported if a number or capitalized phrase is absent from both sentence and paper:
    content_invented = _sourced(
        "Marco Hutter's 2025 paper on Tube Model Predictive Control tested 95 robots",
        input_id=entry.id,
        url="https://rsl.ethz.ch/people/hutter",
    )
    verdicts_invented = verify_letter_claims(
        content_invented, facts={}, inputs={entry.id: entry}, immigration=False
    )
    assert verdicts_invented[0].verdict == Verdict.UNSUPPORTED


def test_sourced_claim_with_titled_person_entity_supports_surname_and_blocks_invented_first_name():
    entry = _research_input(
        entity="Prof. Dr. Marco Hutter", url="https://rsl.ethz.ch/people/hutter"
    )
    entry.provenance.update(
        {
            "kind": "named_person",
            "paper_title": "Tube Model Predictive Control for Quadruped Locomotion",
            "paper_year": 2025,
            "paper_url": "https://doi.org/10.1109/tro.2025.001",
            "paper_finding": "Reduces slip on 25-degree gravel inclines by 40 percent.",
        }
    )
    for valid_text in (
        "Marco Hutter's 2025 paper on Tube Model Predictive Control reduces slip by 40 percent",
        "Prof. Hutter's 2025 paper on Tube Model Predictive Control reduces slip by 40 percent",
        "In his 2025 paper on Tube Model Predictive Control, Hutter reduces slip by 40 percent",
    ):
        verdicts = verify_letter_claims(
            _sourced(valid_text, input_id=entry.id, url="https://rsl.ethz.ch/people/hutter"),
            facts={},
            inputs={entry.id: entry},
            immigration=False,
        )
        assert verdicts[0].verdict == Verdict.SUPPORTED

    wrong_first_name = _sourced(
        "Prof. Anna Hutter's 2025 paper on Tube Model Predictive Control",
        input_id=entry.id,
        url="https://rsl.ethz.ch/people/hutter",
    )
    assert (
        verify_letter_claims(
            wrong_first_name, facts={}, inputs={entry.id: entry}, immigration=False
        )[0].verdict
        == Verdict.UNSUPPORTED
    )



def test_an_input_id_pointing_at_a_non_research_input_is_unsupported():
    entry = NarrativeInput(
        id=uuid4(), kind=NarrativeInput.Kind.RESEARCH_PLAN, text="x",
        proposed_by=NarrativeInput.ProposedBy.STUDENT,
    )
    content = _sourced("the Chair of Robotics", input_id=entry.id)
    verdicts = verify_letter_claims(content, facts={}, inputs={entry.id: entry}, immigration=False)
    assert verdicts[0].verdict == Verdict.UNSUPPORTED


def test_uncertain_sourced_does_not_block_a_non_immigration_letter():
    from apps.documents.letters import is_letter_blocked

    content = _sourced("the robotics lab")
    verdicts = verify_letter_claims(content, facts={}, inputs={}, immigration=False)
    assert not is_letter_blocked(verdicts, (), immigration=False)
    assert is_letter_blocked(verdicts, (), immigration=True)


def test_interpretive_and_aspirational_never_block():
    claims = (
        LetterClaim(
            text="that is why I switched fields",
            span_start=0,
            span_end=30,
            kind=ClaimKind.INTERPRETIVE,
        ),
        LetterClaim(
            text="I hope to lead a research group",
            span_start=0,
            span_end=32,
            kind=ClaimKind.ASPIRATIONAL,
        ),
    )
    content = LetterContent(
        language="en", units=(LetterUnit(archetype="GOALS", text="text", claims=claims),)
    )
    verdicts = verify_letter_claims(content, facts={}, inputs={}, immigration=False)
    assert all(v.verdict == Verdict.SUPPORTED for v in verdicts)


def test_immigration_flag_makes_uncertain_factual_blocking(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "lv4")
        fact = VerifiedFact.objects.create(
            student=student,
            category=VerifiedFact.Category.PERSONAL,
            payload={"ties": "family"},
            source_tier=VerifiedFact.SourceTier.STUDENT_STATEMENT,
            source_ref="c4",
            confirmed_by=None,
            created_by=student,
        )
        claim = LetterClaim(
            text="my family lives in the region",
            span_start=0,
            span_end=30,
            kind=ClaimKind.FACTUAL,
            fact_id=fact.id,
        )
        content = LetterContent(
            language="en",
            units=(
                LetterUnit(
                    archetype="PERSONAL_BACKGROUND",
                    text="my family lives in the region",
                    claims=(claim,),
                ),
            ),
        )
        verdicts = verify_letter_claims(content, facts={fact.id: fact}, inputs={}, immigration=True)
        # UNCERTAIN is the verdict value regardless of immigration -- the
        # immigration flag changes BLOCKING behaviour downstream (Task 6's
        # gate consumes this), not the verdict label itself.
        assert verdicts[0].verdict == Verdict.UNCERTAIN
