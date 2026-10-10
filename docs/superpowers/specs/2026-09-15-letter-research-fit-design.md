# Research fit in the letter: a named group is a sourced fact, the choice is the student's

Status: **superseded 2026-09-22** by `2026-09-22-letter-research-fit-from-the-student-design.md`.
Kept as the record of the crawl-first design: the owner's decisions of 2026-09-22 dissolved its
depth question (search from the student's anchor instead of crawling the site), retracted its
pre-draft confirmation (nothing asked before a draft), and moved storage from the shared catalog to
the student's own `NarrativeInput`. Its Decision 6 survives, restated entity-level in the new spec's
D9. Nothing below authorizes work.

Original status: design, awaiting owner review (2026-09-15). Authorizes planning only.
Date: 2026-09-15.
Amends: `2026-08-22-phase2-motivation-letter-engine-design.md` (the `WHY_PROGRAMME` unit and the
`SOURCED` claim kind) and its plan on branch `claude/phase2-motivation-letter-engine`
(`apps/documents/letters.py`, `letter_gates.py`, `letter_verification.py`, `letter_schemas.py`).
Reads: `docs/research/2026-09-14-letter-storytelling-evidence.md` (N-04, N-15, N-18, N-19) and
`docs/research/letter-rules.csv` (L-028, L-041/042, L-045, L-048, L-062).

## Goal, in three beats

**What and why.** Let a motivation letter say *why this programme* with a real, checkable object:
"I chose the Chair of Robotics' thesis track over the taught route because my thesis on X used the
same Y" — or cite a paper the group's own page lists — when, and only when, the student's verified
research aligns with what the institution publishes about its groups. Today the letter engine's
fit paragraph must carry a `SOURCED` claim (amended 2026-09-14) and has nothing to source it from:
`ApplicationPrompt.programme_evidence` is never populated and never reaches the model, so the gate
is unsatisfiable. This design is what fills it.

**The catch.** A professor's name, a group's name and a paper's title are exactly the things a
committee can check, and the Cambridge rule treats a hallucinated one as fraud that withdraws every
application. So nothing here is asserted by the model: the group and person come as verbatim
sentences verified against the institution's archived page; a paper comes by DOI resolved through
Crossref/OpenAlex, never by name; alignment is a judged, majority-of-three call; and the student
confirms the cross-reference before the letter names anyone. An empty slot beats a guess (N-19).
What this cannot reach is the unpublished — a group's culture, whether a professor is taking
students this year — and the spec says so rather than pretending.

**What it costs to reverse.** One `ProgramStatement.Kind` value and one extractor prompt on the
catalog side; a third data block in the letter prompt; one stricter check in claim verification
that should exist regardless. Removing the feature leaves the stricter check and an unused enum.

## What exists (measured on the letter branch and on master)

- `ClaimKind` has `FACTUAL | DECLARED | SOURCED | INTERPRETIVE | ASPIRATIONAL`
  (`letter_schemas.py`). `check_generic_paragraph` requires a `WHY_PROGRAMME` unit to carry a
  `FACTUAL` or `SOURCED` claim (`letter_gates.py:196-207`).
- **`verify_letter_claims` marks a `SOURCED` claim supported whenever `source_url` is non-empty**
  (`letter_verification.py:36-41`); it never refetches. A claim naming a real person with any
  plausible URL passes today. That is the real gap, and it predates this design.
- `check_claim_coverage` already forces any capitalised multi-word phrase — "Professor Anna
  Schmidt" — inside a declared claim span (`UNDECLARED_ASSERTION`). No new trigger is needed for
  names; the stated ceiling is a lowercase soft claim ("the robotics group").
- Nothing models a person, group, lab or publication attached to a `Program` or `Institution`.
  `ProgramStatement.Kind` is `COMPETENCY | DOCUMENT | FORMAT | LANGUAGE | OTHER`;
  `OfficialEvidenceClaim.ClaimClass` has no academic-profile class, and the 2026-08-28 plan
  deliberately refused to add one.
- `reader.py::extract_statements` reads obligations ("must or should have, hold, submit") and
  `CLAUDE.md` forbids widening its vocabulary; a second extractor needs its own.
- `documents/evidence/publication.py` resolves a DOI through Crossref then OpenAlex mechanically —
  "no model reads anything on this path".
- `derive._THIRD_PARTY` voids any CV-directive candidate that names a supervisor, referee, host or
  professor, because two of three live readings once applied a supervisor's CV requirement to the
  applicant. It lives in the CV-directive path only.
- The owner's line (2026-09-14): *"the boundary is whether a submitted document could check the
  claim. A course, grade, degree, date, employer, institution, publication or number comes only
  from the ledger; the motivation, reasoning, framing and plan around it the engine writes freely."*

## Decisions

1. **A programme's groups and people are `ProgramStatement` rows of a new kind, `RESEARCH`.**
   Verbatim sentences from the institution's own page ("The Chair of Robotics, led by Prof. A.
   Schmidt, hosts master's theses on legged locomotion"), verified against the archived snapshot
   exactly as every other statement is, identity = the sentence, lineage = the snapshot. No new
   table, no new FK. The rows are shared-catalog data with third-party content in them, so the
   `CLAUDE.md` rule applies unchanged: profile only URLs reachable from a catalog-vouched
   `OfficialSource`, same origin, written by the `catalog_ingestion` role.

2. **A second extractor with its own vocabulary, over the programme's page set.** It reads for
   groups, chairs, labs, named faculty, stated research themes and thesis-in-group options, on the
   programme page and the same-origin "people" / "research" pages it links to (depth 1, the same
   page-set widening `2026-09-13-institution-programme-funding-search-design.md` §4.2 introduces for
   funding). It is not a widening of `extract_statements`: a person row in the `COMPETENCY` pool
   would pollute CV tailoring, which reads that kind.

3. **Publications attach by DOI only, and only DOIs printed on the page.** A `RESEARCH` statement
   whose sentence contains a DOI gets that DOI resolved through `publication.py` and stored beside
   it; the letter may cite the resolved title and year. Looking a professor up in OpenAlex by name
   and institution is deliberately not built: name matching is where the wrong person enters, and a
   misattributed paper is the Cambridge fraud class.

4. **Alignment is judged, not asserted.** For each (student, programme) pair the engine compares
   the student's ledger research facts — thesis title and topic, publications, project descriptions
   already in `VerifiedFact` — with the programme's `RESEARCH` statements and asks a closed question
   three times in three phrasings: *does statement S describe work the student's fact F is directly
   about?* Answer: `strong | weak | none` with the cited excerpt of each. Only a majority `strong`
   on the same (F, S) pair produces a proposal. This is §7.3's "anchored qualitative judgement with
   cited excerpts", and the same three-readings discipline the CV-format decision uses.

5. **The student confirms before the letter names anyone.** A proposal surfaces in the letter
   overlay as an engine-proposed `NarrativeInput`: *"Your thesis on legged locomotion matches the
   Chair of Robotics (Prof. Schmidt). Name it in your letter? Have you read their work?"* Accepting
   confirms it (the decision-(c) mechanism N-04 already uses for origin sentences); declining leaves
   the slot empty and `WHY_PROGRAMME` falls back to a module, track or consortium fact (N-15). In the
   letter, the group/person/paper is a `SOURCED` claim, the student's choice and reason is a
   `DECLARED` claim citing that input, and the "so what" is `INTERPRETIVE`. No new claim kind.

6. **`verify_letter_claims` closes the `SOURCED` hole.** A `SOURCED` claim is supported only when
   its anchor text is a normalised substring of the archived snapshot behind its `source_url` —
   the `reader.verified_statements` / `_haystack` machinery, applied one layer later — and the
   `source_url`'s origin matches the target programme's institution (`require_same_origin`). A
   plausible URL is no longer enough. This fixes a pre-existing weakness and is worth shipping alone.

7. **"Over standard coursework" needs a fact too.** The contrast is only available when the
   programme states the alternative: `Program.academic_track == RESEARCH`, or a `RESEARCH` or
   `OTHER` statement establishing a thesis-in-group or research-track option. Without it the
   sentence invents a structure, and the prompt forbids it.

8. **No flattery, no cut-and-paste.** The `SOURCED` sentence connects the group's work to the
   student's; it does not describe the group. At most one short quotation of the page's own words
   (Chevening penalises pasted site copy; Göttingen: "we wrote it, we know it"). The DAAD
   no-flattery rule (L-028) is already in the prompt.

9. **People move; the claim is re-checked at render.** The proposal records the snapshot digest.
   When the letter is rendered for an application, the cited statement must still be present in the
   programme's current read; if the page has dropped it, the render gate marks the claim `undecided`
   and the counselor sees the sentence beside the quote — the same residue path the CV format
   decision uses. A letter never ships a name the page no longer carries.

10. **Third-party personal data is handled, not ignored.** A professor's name reaches a model and
    a shared table. It is published by their employer on its own site about its professional role,
    archived with provenance, holds no special-category data, and is stored only as the verbatim
    sentence. A takedown or correction is a catalog fix by hand, recorded — the same route as a
    moved `canonical_url`. `derive._THIRD_PARTY` is untouched because `RESEARCH` rows never pass
    through `derive_page_rules`; the spec pins that with a test so nobody routes them there later.

## Data flow

```
programme page set ──► research extractor (own vocabulary) ──► verified_statements
                                                                   │
                                         ProgramStatement(kind=RESEARCH) [+ DOI → publication.py]
                                                                   │
student ledger research facts ──► alignment judge ×3 ──► majority strong on (F, S)?
                                                                   │ yes
                                              engine-proposed NarrativeInput in the overlay
                                                                   │ student accepts
letter generation: third DATA block "programme research facts"  ──► WHY_PROGRAMME / RESEARCH_PLAN
                                                                   │
verify_letter_claims: SOURCED anchor ⊂ snapshot ∧ same origin ──► render re-check ──► counselor residue
```

## Data model

- `ProgramStatement.Kind` += `RESEARCH`; the check constraint that re-enumerates kinds is updated;
  one migration.
- `ProgramStatement.doi` (nullable) and `publication` FK (nullable) to a `PublicationRecord` row
  reusing `evidence/publication.py`'s shape — only set when the DOI appears in the sentence.
- `NarrativeInput` gains `proposed_from` (nullable JSON): `{statement_id, fact_id, snapshot_digest,
  judgement}` so an accepted proposal keeps its provenance.
- `ApplicationPrompt.programme_evidence` is **read from** `RESEARCH` statements when the prompt is
  built, never written by hand; the field stops being an orphan.

## Prompt and gates

- `letters._call_model` gets a third labelled DATA block, *programme research facts*, listing the
  accepted (F, S) pairs with their verbatim sentences and resolved DOIs, consumed by `WHY_PROGRAMME`
  and `RESEARCH_PLAN`. The existing no-invention lines cover it; one line is added: *do not describe
  the group; connect its work to the applicant's*.
- `check_claim_coverage`: no change; record that it is load-bearing for names.
- `check_wrong_institution`: the `RESEARCH` statement's institution (its snapshot's) joins the
  letter's expected-institution set, so a professor cited with another affiliation trips it.
- `check_generic_paragraph`: no change; a `RESEARCH`-backed `SOURCED` claim is what satisfies it.
- `verify_letter_claims`: decision 6.
- Hygiene: no change — `normalize_text` never touches letters or diacritics, so "Ångström" and
  "Ș" survive.

## Cost

One extractor read per programme page set on the reader's existing cadence and cache
(`content_sha256`), rate-limited like `read_program_page`. Three short judgement calls per
(student, programme) pair, once per letter, behind a new per-student limiter (`research-fit`,
20/hour) on top of generation's own. No call at render time: the re-check compares digests.

## Testing

- Extractor: a fixture people-page yields `RESEARCH` rows whose text is on the page; a sentence
  not on the page is dropped and counted; a row never lands in the `COMPETENCY` pool (tailoring
  fixture unchanged).
- Judge: the same fixture pair judged three times; a 2-of-3 `strong` proposes, 1-of-3 does not;
  a `weak` majority proposes nothing.
- Overlay: a declined proposal leaves no `SOURCED` research claim; an accepted one produces
  `SOURCED` + `DECLARED` + `INTERPRETIVE` spans that pass `check_claim_coverage`.
- Verification: a `SOURCED` claim with a plausible URL but no anchor on the snapshot is
  `UNSUPPORTED` (the negative control that proves decision 6); an off-origin URL is `UNSUPPORTED`.
- Render re-check: remove the statement from the current read → `undecided`, counselor residue.
- Isolation: `RESEARCH` rows are shared-catalog; a test asserts `derive_page_rules` never sees
  them; another asserts no `IDENTITY` fact of the student enters the judge prompt (the
  `tailoring.fact_pool` precedent).
- One live gate, `-m live`: a real programme page with a real people page; three reads must
  agree on the group name; the DOI on the page must resolve.

## Deliberately not built

- **OpenAlex author lookup by name** — the wrong-person path. Trigger to revisit: a measured
  sample where page-printed DOIs are too rare to be useful.
- **Contacting the professor.** Never; N-19.
- **Supervisor matching for MEXT / CSC / GKS** beyond what their pages state — those funders do not
  require a named supervisor (L-010, the 2026-08-22 ruleset) and the feature must not make one
  mandatory.
- **Inferring group culture, openness to students, or funding from proximity** — §2 forbids the
  last by name; the others are the "honest residual" the letter spec already records.

## Open decisions for the owner

1. **Ask the student "have you read their work?"** as a confirmation gate (recommended — it keeps
   the letter honest under interview follow-up), or accept on the alignment match alone?
2. **Scope of the people pages**: programme page + linked same-origin pages at depth 1
   (recommended), or programme page only?
3. **Ship decision 6 (the `SOURCED` verification fix) ahead of the rest** on the letter branch? The
   design recommends yes; it is independent and closes a live hole.
