from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

_CONTENT_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class ClaimKind(StrEnum):
    FACTUAL = "FACTUAL"
    DECLARED = "DECLARED"
    INTERPRETIVE = "INTERPRETIVE"
    ASPIRATIONAL = "ASPIRATIONAL"
    SOURCED = "SOURCED"


_REQUIRED_ID_FIELD = {
    ClaimKind.FACTUAL: "fact_id",
    ClaimKind.DECLARED: "input_id",
    ClaimKind.SOURCED: "source_url",
}
_ID_FIELDS = ("fact_id", "input_id", "source_url")


class LetterClaim(BaseModel):
    model_config = _CONTENT_CONFIG

    text: str = Field(min_length=1, max_length=2_000)
    #: The span is a SENTENCE range, not a quote range. `text` may be a short
    #: phrase inside a longer sentence; the span must still enclose every
    #: whole sentence that phrase supports, because that is what
    #: letter_gates.check_claim_coverage measures -- a sentence carrying a
    #: number, a date or a proper-noun phrase is an undeclared assertion
    #: unless some provenance-bearing claim's span encloses it end to end.
    #: letter_render.hygienic_letter_content re-anchors both offsets onto the
    #: cleaned text's sentence bounds, so a span that is merely inside the
    #: right sentence is widened rather than rejected; nothing in this schema
    #: relates either offset to the unit's text, so a span pointing outside
    #: it is not a validation error, it is a claim that covers nothing.
    span_start: int = Field(
        ge=0,
        description=(
            "Character offset in the unit's text where the sentence(s) this claim supports "
            "begin. Must enclose whole sentences, not just the quoted phrase in `text`."
        ),
    )
    span_end: int = Field(
        ge=0,
        description=(
            "Character offset in the unit's text just past the end of the last sentence this "
            "claim supports. Must enclose whole sentences, not just the quoted phrase in `text`."
        ),
    )
    kind: ClaimKind
    fact_id: UUID | None = None
    input_id: UUID | None = None
    source_url: str | None = Field(default=None, min_length=1, max_length=2048)

    @model_validator(mode="after")
    def _exactly_the_required_id(self) -> LetterClaim:
        required = _REQUIRED_ID_FIELD.get(self.kind)
        # A SOURCED claim cites its URL and MAY cite the research-fit input
        # that verified the sentence (D9). A student-typed name is never
        # SOURCED: it is DECLARED with an input_id, and the fabrication gate
        # exists to stop the model inventing, never to second-guess the
        # student (engine design decision 8; owner decision 2026-09-22).
        allowed = {required} | ({"input_id"} if self.kind == ClaimKind.SOURCED else set())
        for field_name in _ID_FIELDS:
            value = getattr(self, field_name)
            if field_name == required and value is None:
                raise ValueError(f"{self.kind} claim requires {required}")
            if field_name not in allowed and value is not None:
                raise ValueError(f"{self.kind} claim must not set {field_name}")
        return self


class LetterUnit(BaseModel):
    model_config = _CONTENT_CONFIG

    archetype: str = Field(min_length=1, max_length=40)
    answers_question: str | None = Field(default=None, max_length=50)
    text: str = Field(min_length=1, max_length=5_000)
    claims: tuple[LetterClaim, ...] = ()


class Storyline(BaseModel):
    """The one story a core narrative tells (Task 11b). Everything here is
    the engine's interpretation of ledger facts -- the theme, the order, the
    turn, the gap, the assumptions -- and nothing here is a fact: anchors are
    ids into the ledger, never text, so the story cannot smuggle in a claim."""

    model_config = _CONTENT_CONFIG

    theme: str = Field(min_length=1, max_length=1_000)
    theme_kind: str = Field(min_length=1, max_length=80)
    anchors: tuple[UUID, ...] = Field(min_length=1, max_length=12)
    turn: UUID | None = None
    gap: str | None = Field(default=None, max_length=1_500)
    assumptions: tuple[str, ...] = Field(default=(), max_length=6)
    future: str = Field(min_length=1, max_length=1_000)


class LetterContent(BaseModel):
    model_config = _CONTENT_CONFIG

    schema_version: int = Field(default=1, ge=1)
    language: str = Field(min_length=2, max_length=10)
    header_block: str | None = Field(default=None, max_length=300)
    units: tuple[LetterUnit, ...] = Field(max_length=30)
    storyline: Storyline | None = None


class SentenceClaimBinding(BaseModel):
    """Sentence-level claim attribution without LLM character-offset arithmetic
    (Slobodkin et al. 2024 ACL 'Attribute First, Then Generate')."""

    model_config = _CONTENT_CONFIG

    kind: ClaimKind
    text: str | None = Field(default=None, max_length=2_000)
    fact_id: UUID | None = None
    input_id: UUID | None = None
    source_url: str | None = Field(default=None, min_length=1, max_length=2048)


class AttributedSentence(BaseModel):
    model_config = _CONTENT_CONFIG

    text: str = Field(min_length=1, max_length=2_000)
    claims: tuple[SentenceClaimBinding, ...] = ()


class SentenceAttributedUnit(BaseModel):
    model_config = _CONTENT_CONFIG

    archetype: str = Field(min_length=1, max_length=40)
    answers_question: str | None = Field(default=None, max_length=50)
    sentences: tuple[AttributedSentence, ...] = Field(min_length=1, max_length=30)


class SentenceAttributedLetterContent(BaseModel):
    model_config = _CONTENT_CONFIG

    schema_version: int = Field(default=1, ge=1)
    language: str = Field(min_length=2, max_length=10)
    header_block: str | None = Field(default=None, max_length=300)
    units: tuple[SentenceAttributedUnit, ...] = Field(max_length=30)
    storyline: Storyline | None = None


def compile_attributed_letter_content(
    attributed: SentenceAttributedLetterContent,
) -> LetterContent:
    """Compile sentence-attributed units into `LetterContent` with exact
    `[span_start, span_end)` sentence offsets by construction."""
    compiled_units: list[LetterUnit] = []
    for unit in attributed.units:
        parts: list[str] = []
        claims: list[LetterClaim] = []
        cursor = 0
        for idx, sent in enumerate(unit.sentences):
            if idx > 0:
                parts.append(" ")
                cursor += 1
            sent_text = sent.text.strip()
            sent_start = cursor
            sent_end = sent_start + len(sent_text)
            parts.append(sent_text)
            cursor = sent_end
            for binding in sent.claims:
                claims.append(
                    LetterClaim(
                        text=(binding.text or sent_text).strip() or sent_text,
                        span_start=sent_start,
                        span_end=sent_end,
                        kind=binding.kind,
                        fact_id=binding.fact_id,
                        input_id=binding.input_id,
                        source_url=binding.source_url,
                    )
                )
        compiled_units.append(
            LetterUnit(
                archetype=unit.archetype,
                answers_question=unit.answers_question,
                text="".join(parts),
                claims=tuple(claims),
            )
        )
    return LetterContent(
        schema_version=attributed.schema_version,
        language=attributed.language,
        header_block=attributed.header_block,
        units=tuple(compiled_units),
        storyline=attributed.storyline,
    )
