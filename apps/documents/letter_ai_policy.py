"""Reference data only (spec decision 6): never a generation or approval
gate. See test_letter_ai_policy.py's source-grep test, which asserts this
module is not imported by any gate/generation/approval module -- keep that
invariant if you add new AI-policy entries here."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from apps.funding.models import ApplicationPrompt


class AIUsePolicyClass(StrEnum):
    PROHIBITS = "PROHIBITS"
    REQUIRES_DISCLOSURE = "REQUIRES_DISCLOSURE"
    IMMIGRATION_PROHIBITION = "IMMIGRATION_PROHIBITION"
    SILENT = "SILENT"


@dataclass(frozen=True)
class AIUsePolicyNote:
    policy_class: AIUsePolicyClass
    note_text: str


_SILENT_DEFAULT = AIUsePolicyNote(AIUsePolicyClass.SILENT, "nothing found is not permission")

AI_POLICY_TABLE: dict[str, AIUsePolicyNote] = {
    "cambridge": AIUsePolicyNote(
        AIUsePolicyClass.PROHIBITS,
        (
            "AI must not be used when writing personal statements and CVs, including help with "
            "English. Hallucinated achievements are treated as application fraud. Research "
            "proposals: AI is permitted with acknowledgement."
        ),
    ),
    "oxford": AIUsePolicyNote(
        AIUsePolicyClass.PROHIBITS,
        (
            "AI-generated material counts as plagiarism; the statement must be entirely the "
            "applicant's own work; departments may screen with plagiarism-detection software "
            "that can also detect AI usage."
        ),
    ),
    "edinburgh": AIUsePolicyNote(
        AIUsePolicyClass.PROHIBITS,
        (
            "Asking someone else to write your statement or using AI apps such as ChatGPT "
            "could be considered fraud."
        ),
    ),
    "chevening": AIUsePolicyNote(
        AIUsePolicyClass.PROHIBITS,
        (
            "AI use is strictly prohibited and detection tools are used. Chevening does not "
            "endorse or work with third parties who charge for application support."
        ),
    ),
    "rhodes": AIUsePolicyNote(
        AIUsePolicyClass.REQUIRES_DISCLOSURE,
        (
            "Mentors must not write or edit the statement. The applicant attests the statement "
            "is their own original experiences, thinking and judgment, even where AI tools "
            "supported expression. Every helper, and for GenAI the specific tool and prompts, "
            "must be disclosed. AI must not generate substantive content."
        ),
    ),
    "daad": AIUsePolicyNote(
        AIUsePolicyClass.REQUIRES_DISCLOSURE,
        (
            "AI is permitted as an aid. Passages must carry the note 'Produced with the aid of "
            "(tool used)'. A Declaration of Authenticity states the application was prepared "
            "independently."
        ),
    ),
    "australia_gs": AIUsePolicyNote(
        AIUsePolicyClass.IMMIGRATION_PROHIBITION,
        (
            "Do not modify or create documents using digital editing tools, artificial "
            "intelligence (AI), or any other method. Misrepresentation may lead to visa "
            "refusal, cancellation, future restrictions and legal action."
        ),
    ),
    "canada_ircc": AIUsePolicyNote(
        AIUsePolicyClass.IMMIGRATION_PROHIBITION,
        (
            "Misrepresentation, including by a representative acting for the applicant with or "
            "without the applicant's knowledge, brings five years' inadmissibility under "
            "IRPA s.40."
        ),
    ),
}


def resolve_ai_use_policy(funder_id: str | None) -> AIUsePolicyNote:
    if funder_id is None:
        return _SILENT_DEFAULT
    return AI_POLICY_TABLE.get(funder_id.strip().casefold(), _SILENT_DEFAULT)


_ALIAS_TO_POLICY_KEY: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"\b(?:university\s+of\s+cambridge|cambridge\.ac\.uk)\b", re.IGNORECASE),
        "cambridge",
    ),
    (re.compile(r"\b(?:university\s+of\s+oxford|ox\.ac\.uk)\b", re.IGNORECASE), "oxford"),
    (re.compile(r"\b(?:university\s+of\s+edinburgh|ed\.ac\.uk)\b", re.IGNORECASE), "edinburgh"),
    (re.compile(r"\bchevening\b", re.IGNORECASE), "chevening"),
    (
        re.compile(r"\b(?:rhodes\s+scholarship|rhodes\s+trust|rhodeshouse)\b", re.IGNORECASE),
        "rhodes",
    ),
    (
        re.compile(
            r"\b(?:daad|deutscher\s+akademischer\s+austauschdienst)\b",
            re.IGNORECASE,
        ),
        "daad",
    ),
)

_AI_MENTION_RE = re.compile(
    r"\b(?:artificial\s+intelligence|generative\s+ai|genai|chatgpt|large\s+language\s+models?|"
    r"llms?|ai[-\s]generated|ai\s+tools?|ai\s+apps?|ai\s+assistance)\b",
    re.IGNORECASE,
)
_AI_PROHIBIT_RE = re.compile(
    r"\b(?:prohibit(?:ed|s)?|not\s+(?:be\s+)?(?:permitted|allowed|used|acceptable)|"
    r"must\s+not|do\s+not\s+use|plagiarism|fraud|strictly\s+forbidden|"
    r"entirely\s+(?:your|the\s+applicant's)\s+own\s+work)\b",
    re.IGNORECASE,
)
_AI_DISCLOSURE_RE = re.compile(
    r"\b(?:disclos(?:e|ed|ure)|acknowledg(?:e|ed|ement)|declare|declaration|"
    r"produced\s+with\s+the\s+aid\s+of|state\s+how\s+ai|permitted\s+as\s+an\s+aid)\b",
    re.IGNORECASE,
)


def resolve_prompt_ai_policy(prompt: ApplicationPrompt) -> AIUsePolicyNote:
    """Resolve the advisory AI-use policy note for `prompt` from `AI_POLICY_TABLE`,
    institution/funder aliases, immigration flags, and extracted programme requirements."""
    direct = resolve_ai_use_policy(getattr(prompt, "funder_id", None))
    if direct.policy_class != AIUsePolicyClass.SILENT:
        return direct

    programme = getattr(prompt, "programme", None)
    institution = getattr(programme, "institution", None) if programme is not None else None
    header_parts = [
        str(getattr(institution, "name", "") or ""),
        str(getattr(programme, "name", "") or ""),
        str(getattr(prompt, "source_url", "") or ""),
    ]
    header_blob = " ".join(p for p in header_parts if p)
    for pattern, key in _ALIAS_TO_POLICY_KEY:
        if pattern.search(header_blob):
            return AI_POLICY_TABLE[key]

    if getattr(prompt, "immigration", False):
        country_code = str(getattr(programme, "country_code", "") or "").upper()
        if country_code == "AU":
            return AI_POLICY_TABLE["australia_gs"]
        if country_code == "CA":
            return AI_POLICY_TABLE["canada_ircc"]
        return AIUsePolicyNote(
            AIUsePolicyClass.IMMIGRATION_PROHIBITION,
            (
                "Immigration statements are subject to statutory misrepresentation rules; "
                "AI-generated material may be treated as fraud or misrepresentation."
            ),
        )

    texts: list[str] = []
    for req in getattr(prompt, "letter_written_requirements", None) or ():
        if isinstance(req, dict) and req.get("text"):
            texts.append(str(req["text"]))
        elif isinstance(req, str) and req:
            texts.append(req)
    for text in texts:
        if not _AI_MENTION_RE.search(text):
            continue
        cleaned = " ".join(text.split())[:300]
        if _AI_PROHIBIT_RE.search(text):
            return AIUsePolicyNote(AIUsePolicyClass.PROHIBITS, cleaned)
        if _AI_DISCLOSURE_RE.search(text):
            return AIUsePolicyNote(AIUsePolicyClass.REQUIRES_DISCLOSURE, cleaned)

    return _SILENT_DEFAULT
