"""Hand-synthesized ApplicationPrompt records for the ~25 funders researched
in docs/research/2026-08-22-letter-ruleset.md. Each entry cites the L-xxx
rows it synthesizes in a comment. Extend by hand, one funder at a time --
this is data population, not a mechanical parse (see the plan task's note
on why letter-rules.csv can't be parsed row-to-field the way
cv-rules.csv's cv_format_requirement loader is).

Populating the ~25 researched funders is out of scope for this task -- see
the plan's "Open follow-ups" -- so this module ships with no live entries.
"""

# A live entry uses ApplicationPrompt.FunderKind / .Structure for funder_kind
# and structure -- import it here once the first real fixture is added below.
LETTER_PROMPT_FIXTURES: dict[str, dict[str, object]] = {
    # Example, cites L-001-L-007, L-059, L-071:
    # "australia-gs": {
    #     "lookup": {"canonical_key": "..."},
    #     "cycle": "2026", "source_url": "https://immi.homeaffairs.gov.au/...",
    #     "confidence": 1.0, "verified_for_cycle": "2026",
    #     "funder_kind": ApplicationPrompt.FunderKind.IMMIGRATION_AUTHORITY,
    #     "structure": ApplicationPrompt.Structure.SHORT_ANSWER_SET,
    #     "archetypes": [
    #         "WHY_PROGRAMME", "WHY_COUNTRY", "PERSONAL_BACKGROUND", "CAREER_PLAN_RETURN",
    #     ],
    #     "questions": [
    #         {
    #             "id": "q1", "text": "current circumstances",
    #             "archetypes": ["PERSONAL_BACKGROUND"], "max_words": 150,
    #         },
    #         {
    #             "id": "q2", "text": "why this course in Australia",
    #             "archetypes": ["WHY_PROGRAMME", "WHY_COUNTRY"], "max_words": 150,
    #         },
    #         {
    #             "id": "q3", "text": "benefit of completing the course",
    #             "archetypes": ["CAREER_PLAN_RETURN"], "max_words": 150,
    #         },
    #         {
    #             "id": "q4", "text": "other relevant information",
    #             "archetypes": [], "max_words": 150,
    #         },
    #     ],
    #     "programme_evidence": {}, "document_language": "en",
    #     "header_block_required": False,
    # },
}
