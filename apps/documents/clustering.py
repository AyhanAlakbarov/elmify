"""Task 11: letter clustering -- cluster key, reuse decision, regeneration set.

Given a resolved ``ApplicationPrompt`` (Task 2/9), decide which other letters'
generated content this one can reuse (``cluster_key``/``is_reusable``) and
which archetypes must always be regenerated per-programme rather than shared
across a cluster (``units_to_regenerate``).

PF-4: ``ApplicationPrompt`` has no ``constraints`` field. Word/char limits
come from ``prompt.questions[]`` only (each question may carry a
``max_words`` and/or ``max_chars_incl_spaces`` key), matching the resolved
ambiguity in the pre-port branch's ``_limit``.
"""

from __future__ import annotations

from typing import Any

CORE_ELIGIBLE_ARCHETYPES = frozenset({
    "PERSONAL_BACKGROUND",
    "ACADEMIC_PREPARATION",
    "LEADERSHIP_EXAMPLE",
    "RELATIONSHIP_COMMUNITY",
    "CAREER_PLAN_RETURN",
    "HOME_COUNTRY_CONTRIBUTION",
})

ALWAYS_REGENERATED_ARCHETYPES = frozenset({
    "OPENING", "CLOSING", "WHY_PROGRAMME", "WHY_COUNTRY", "RESEARCH_PLAN", "LANGUAGE_PLAN",
})

_SHORT_WORDS, _MEDIUM_WORDS = 300, 800
_SHORT_CHARS, _MEDIUM_CHARS = 2_000, 6_000


def _limit(prompt: Any, key: str) -> int | None:
    """Sum a positive-int question field across ``prompt.questions``, or None."""
    per_question = [v for q in prompt.questions if isinstance(v := q.get(key), int) and v > 0]
    return sum(per_question) if per_question else None


def _band(value: int, short: int, medium: int) -> str:
    if value <= short:
        return "SHORT"
    if value <= medium:
        return "MEDIUM"
    return "LONG"


def word_limit_band(prompt: Any) -> str:
    """Bucket a prompt's word/char limit into SHORT/MEDIUM/LONG, prefixed by
    ``prompt.structure`` so a short-answer set and a long letter never
    cluster together even at the same word count."""
    words = _limit(prompt, "max_words")
    if words is not None:
        size = _band(words, _SHORT_WORDS, _MEDIUM_WORDS)
    else:
        chars = _limit(prompt, "max_chars_incl_spaces")
        size = _band(chars, _SHORT_CHARS, _MEDIUM_CHARS) if chars is not None else "UNKNOWN"
    return f"{prompt.structure}:{size}"


def cluster_key(prompt: Any, *, discipline: str, scholarship_present: bool) -> tuple[object, ...]:
    """The reuse key for a resolved prompt. ``discipline``/``scholarship_present``
    come from Program/FundingOpportunity, never from ApplicationPrompt itself."""
    return (
        discipline,
        prompt.structure,
        tuple(sorted(prompt.archetypes)),
        word_limit_band(prompt),
        scholarship_present,
        prompt.document_language,
    )


def is_reusable(a_key: tuple[object, ...], b_key: tuple[object, ...]) -> bool:
    return a_key == b_key


def units_to_regenerate(archetypes: tuple[str, ...]) -> tuple[str, ...]:
    """Every archetype not core-eligible: always-regenerated plus anything
    uncategorised -- fail toward regenerating, never toward silently reusing
    an unrecognised archetype."""
    return tuple(a for a in archetypes if a not in CORE_ELIGIBLE_ARCHETYPES)
