from uuid import uuid4

import pytest
from pydantic import ValidationError

from apps.documents.letter_schemas import (
    ClaimKind,
    LetterClaim,
    LetterContent,
    Storyline,
)


def test_factual_claim_requires_fact_id_only():
    claim = LetterClaim(
        text="I completed a BSc in 2024",
        span_start=0,
        span_end=25,
        kind=ClaimKind.FACTUAL,
        fact_id=uuid4(),
    )
    assert claim.input_id is None and claim.source_url is None


def test_factual_claim_without_fact_id_rejected():
    with pytest.raises(ValidationError):
        LetterClaim(text="x", span_start=0, span_end=1, kind=ClaimKind.FACTUAL)


def test_declared_claim_requires_input_id_only():
    claim = LetterClaim(
        text="I plan to study transfer learning",
        span_start=0,
        span_end=30,
        kind=ClaimKind.DECLARED,
        input_id=uuid4(),
    )
    assert claim.fact_id is None and claim.source_url is None


def test_sourced_claim_requires_source_url_only():
    claim = LetterClaim(
        text="The programme's robotics lab",
        span_start=0,
        span_end=25,
        kind=ClaimKind.SOURCED,
        source_url="https://tum.de/robotics",
    )
    assert claim.fact_id is None and claim.input_id is None


def test_sourced_claim_without_url_rejected():
    with pytest.raises(ValidationError):
        LetterClaim(text="x", span_start=0, span_end=1, kind=ClaimKind.SOURCED)


def test_interpretive_claim_carries_no_id_at_all():
    claim = LetterClaim(
        text="that is why I switched fields",
        span_start=0,
        span_end=30,
        kind=ClaimKind.INTERPRETIVE,
    )
    assert claim.fact_id is None and claim.input_id is None and claim.source_url is None


def test_interpretive_claim_with_a_fact_id_rejected():
    with pytest.raises(ValidationError):
        LetterClaim(
            text="x", span_start=0, span_end=1, kind=ClaimKind.INTERPRETIVE, fact_id=uuid4()
        )


def test_letter_content_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        LetterContent(language="en", units=(), extra="nope")


def test_letter_content_is_frozen():
    content = LetterContent(language="en", units=())
    with pytest.raises(ValidationError):
        content.language = "de"


def test_storyline_rejects_unknown_field():
    with pytest.raises(ValidationError):
        Storyline(
            theme="A problem I solved",
            theme_kind="PROBLEM",
            anchors=(uuid4(),),
            future="I will keep solving it",
            extra="nope",
        )


def test_letter_content_round_trips_with_and_without_storyline():
    without = LetterContent(language="en", units=())
    assert without.storyline is None

    storyline = Storyline(
        theme="A problem I solved",
        theme_kind="PROBLEM",
        anchors=(uuid4(),),
        future="I will keep solving it",
    )
    with_storyline = LetterContent(language="en", units=(), storyline=storyline)
    assert with_storyline.storyline == storyline
