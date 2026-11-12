"""Hand-synthesized ApplicationPrompt records for the ~25 funders researched
in docs/research/2026-08-22-letter-ruleset.md. Each entry cites the L-xxx
rows it synthesizes in a comment. Extend by hand, one funder at a time --
this is data population, not a mechanical parse (see the plan task's note
on why letter-rules.csv can't be parsed row-to-field the way
cv-rules.csv's cv_format_requirement loader is).

Populating the ~25 researched funders is out of scope for this task -- see
the plan's "Open follow-ups" -- so this module ships with no live entries.

**Owner decision, 2026-09-24: this is NOT the plan and the ~25 funders are
not to be typed in.** There should be no by-hand rule population -- the
automatic path (a page read deriving the letter's shape alongside the CV's
rules, one model call over the same page) is the mechanism, and it is expected
to cover these funders too. This module stays because it is the only writer of
the VERIFIED tier, which is the seam a human CONFIRMING one prompt would use;
it is not a place to bulk-enter research. The blockers below are kept as the
record of why bulk entry was never possible anyway.

**Two things blocked populating it, and neither was typing speed. Read these
before writing the first fixture, because a file full of them would load
nothing.**

1. **There are no `Program` rows to attach a prompt to.** `load_application_prompts`
   does `Program.objects.get(**lookup)`, and nothing seeds that table:
   `catalog_seed.SEED_FUNDERS` creates `FundingOpportunity` rows (funders),
   and `Program` rows come from discovery, which has no production caller.
   Every fixture written today would take the loader's "no Program matches
   lookup" branch. So the prerequisite is programmes in the catalogue -- either
   discovery wired, or a deliberate seed for the handful this engine is aimed
   at.

2. **Several of the researched funders are not programme-scoped, and
   `ApplicationPrompt.programme` is a non-null FK.** Australia's Genuine
   Student question set (L-001-L-007) is a *visa* requirement that applies to
   every Australian programme; CSC (L-008-L-010) and MEXT (L-011) are
   funder-level forms spanning many universities. Attaching one of those to a
   single `Program` records it as a fact about that programme, which is false
   and quietly wrong for the other programmes it also governs. That is a model
   question -- a funder- or country-scoped prompt, or a documented convention
   for synthesising one -- and it wants deciding before the data is entered,
   not after twenty-five rows exist under whichever convention the first
   fixture happened to pick.

The consequence of both, stated plainly so it is not mistaken for a small
backlog item: **every letter resolves to inferred defaults today**, and will
until the catalogue has programmes. `prompt_resolution` fails closed to
`UNRESOLVED` -> `silent_funder` defaults, which is the right behaviour and not
a substitute for the research being loaded.
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
