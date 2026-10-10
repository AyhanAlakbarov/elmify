"""Reference data only (spec decision 6): never a generation or approval
gate. See test_letter_ai_policy.py's source-grep test, which asserts this
module is not imported by any gate/generation/approval module -- keep that
invariant if you add new AI-policy entries here."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


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
    return AI_POLICY_TABLE.get(funder_id, _SILENT_DEFAULT)
