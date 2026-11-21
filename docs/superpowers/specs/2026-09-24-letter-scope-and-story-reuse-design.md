# Letter scope and story reuse

**Date:** 2026-09-24
**Status:** design, awaiting owner review
**Research it rests on:** `docs/research/2026-09-24-application-shapes.csv` and its note;
`docs/research/2026-09-14-letter-storytelling-evidence.md` (N-10, N-15); `letter-rules.csv`
L-020, L-061, L-068.

## 1. Goal

Two things, in this order.

**A student tells one story.** A student applying to eight programmes should be recognisably
one person across all eight, not eight slightly different people. The owner ranked this first,
and it makes reuse a feature rather than an optimisation — a wrong match is not merely wasted
money, it is a letter that misframes the applicant.

**And it should not cost eight times.** Second, and genuinely second.

## 1a. The method is already built. This design wires it.

**An earlier draft of this spec proposed building pack-level story generation. That was
reinventing `apps/documents/storyline.py`, which is better than the replacement.** Correcting
the record, because the rest of this design rests on it:

| Piece | State |
|---|---|
| `DocumentDraft.Kind.CORE_NARRATIVE` — the student's story as its own document | exists |
| `storyline.propose_storylines` — asks the model for **three** candidate stories | exists |
| `storyline.choose_storyline` — picks one **deterministically**, never the model | exists |
| `storyline.theme_kind_for(funder_kind, archetypes)` — N-10's reader-dependent theme | exists |
| `storyline.recent_theme_texts` — diversity against the tenant's recent stories | exists |
| `letter_gates.check_storyline_drift` — the letter must use the story's anchor facts | exists |
| `generate_letter(core_narrative=…, storyline=…)` — pinning and story both accepted | exists |
| The storyline persisted at `DocumentDraft.content["storyline"]` | exists |
| **Any caller of any of it** | **none** |

Two of those deserve emphasis because a naive design loses them. The model **proposes and never
picks**: one call choosing the theme, the order and the turning point makes the most probable
story — the childhood-passion cliché — the default across every letter. And `choose_storyline`
scores candidates by evidence (anchors, distinct fact categories, minus assumptions) *and*
against `recent_theme_texts`, so the same story does not repeat across an agency's students.

So the scope of this design is: **wire what exists, add the one thing that does not, and fix the
cost.** Not a new composition method.

### What the archival-CV ("Harvard") method does and does not give us

Keeping every fact with its source and tailoring per destination is the right *storage*
arrangement, it is what makes claim-checking possible at all, and the platform already has it.
It is **not** the letter method, and this spec does not cite it as a reason the letters will be
good:

- it is advice for a person, whose problem is forgetting, which a machine does not have;
- it says nothing about *selection*, which is the whole difficulty — that is what
  `propose_storylines`/`choose_storyline` is for;
- and DAAD explicitly penalises "repeating the CV", so a letter assembled by picking items out
  of an archive is at risk of being exactly what the reader marks down.

The letter method is the storytelling findings (N-10 to N-19) and the module that implements
them.

## 2. What the research changed

The engine models one letter per programme. Three shapes exist, and it can express one.

| Scope | Rule | Sourced example |
|---|---|---|
| `PER_PROGRAMME` | one letter per programme | Sciences Po ("two motivation letters in separate sections"), KTH, Finland |
| `SHARED_RANKED` | one letter covering all chosen programmes, ranking them inside it | DAAD Helmut-Schmidt ("a single letter of motivation (even when applying for two master's courses)… You must submit the same letter of motivation to both"), DAAD EPOS |
| `FIRST_CHOICE_ONLY` | several choices, one letter, addressing the first only | Chevening (three different courses required; essays on the first-choice course) |

The fee unit is recorded in the research and is **deliberately not modelled**: it drives no
letter logic, and it does not correlate with the letter count (uni-assist charges per
programme, Sciences Po charges once for two, and both want a letter per programme).

## 3. Data model

Two changes. Both are additive, both default to today's behaviour.

**`ApplicationPrompt.letter_scope`** — `CharField(max_length=18, default="PER_PROGRAMME")`
with those three values and a check constraint, in the `funding` app beside the other
`letter_*` columns. Derived by the page reader like every other shape field, so a page stating
"one letter for both courses" writes `SHARED_RANKED`; absent evidence it stays
`PER_PROGRAMME`, which is the shape that breaks no rule anywhere (§5 of the shape design).

**That derivation is not free and this design does not hide it:** `letter_scope` is a fourth
thing the judge must answer, so `LetterVerdict` gains a field and the closed question gains a
phrasing, and both go through the same three-readings-must-agree bar as every other derived
letter value. Until that lands, the column is written by nothing and every prompt is
`PER_PROGRAMME` — which is exactly today's behaviour, so the model change is safe to ship
before the derivation does.

**`DocumentDraft.covered_programmes`** — an ordered JSON list of programme ids, empty by
default, meaning "just `programme`". When non-empty it holds **every** covered programme in
rank order **including the first**, and its first element always equals `programme`; a test
pins that, because two places holding the first choice is exactly how they drift apart.
`DocumentDraft.programme` stays as the first choice, so every existing query keeps working and
`PER_PROGRAMME` drafts are untouched.

Why JSON and not a through table: the ranking is an *input to generation*, not a fact anything
queries — no screen, gate or report asks "which drafts cover programme X". A through table is
the right upgrade the first time something does; until then it is a table, two migrations and a
join bought for nothing. Ordered, because DAAD requires the courses ranked inside the letter.

## 4. Generation: the pack is the unit

Owner decision: every letter in a recommendation pack is written when the pack is built, so the
student opens a pack that is ready. §38 publishes the pack un-gated by counsellor review, so
there is no approval step to wait for.

The loop is assembly of existing parts, not new machinery:

```
build_pack
  └── for each theme kind present in the pack (theme_kind_for(funder_kind, archetypes)):
        propose_storylines  ->  choose_storyline          (3 candidates, deterministic pick)
        write ONE CORE_NARRATIVE draft carrying that storyline
        └── for each programme with that theme kind:
              if a letter already covers it (SHARED_RANKED): skip
              if another programme at the SAME university already used this core narrative:
                  propose/choose again, excluding the used theme, and write a second
                  CORE_NARRATIVE draft
              generate_letter(core_narrative=…, storyline=…)   -> MOTIVATION_LETTER draft
```

Three rules inside that, each with its reason:

- **Once per theme kind, not once per student.** `theme_kind_for` already returns PROBLEM for a
  research supervisor, PROBLEM or MATCH for university admission depending on whether a research
  plan is asked for, PLAN for scholarship kinds, and **None for immigration and consortium — no
  story at all**. That last case is existing behaviour this design must not break: an
  immigration letter gets no storyline, and `check_storyline_drift` passes trivially when the
  storyline is None.
- **Never the same core narrative twice at one university.** Owner's rule. Checkable via
  `Program.institution_id`. Department is **not** recorded anywhere, so this enforces "different
  university", the safe side of the rule. The second narrative is obtained by choosing again
  with the used theme added to `recent_themes` — the diversity mechanism that already exists,
  rather than a new one.
- **Reuse across universities is permitted outright.** L-061: no admissions office or funder was
  found that penalises reusing a core letter. This was previously guarded on an unsourced worry.

`units_to_regenerate` already decides which paragraphs are pinned and which are rewritten: the
six core-eligible archetypes are the story, and `OPENING`, `CLOSING`, `WHY_PROGRAMME`,
`WHY_COUNTRY`, `RESEARCH_PLAN`, `LANGUAGE_PLAN` are always regenerated. N-15's gate already
refuses a `WHY_PROGRAMME` unit with no sourced claim, so the programme-facing half cannot
quietly become generic.

**`cluster_key` loses its subject argument and the idea behind it.** A published subject
taxonomy (ISCED-F was the phase-2 recommendation) is coarser than the thing that decides
framing: chemoinformatics has no code of its own and lands beside programmes needing a different
letter, and two chemoinformatics programmes differ from each other. A false match reuses a story
that does not fit — worse than not reusing. The key becomes theme kind, structure, language,
length band and archetype set; the same-university refusal sits beside it rather than inside it,
because it is a "must differ" and the rest are "must match".

**Two rate limiters, not one.** `propose_storylines` carries its own (`storyline`, 10/hour per
student) on top of generation's 20/hour. A pack trips both — see §7.

## 5. Cost

Per letter today, roughly: 2 calls to write, up to 6 for the written-requirement check, up to
28 for research fit, plus vendor fetch credits. Research fit is about 80% of it, so the story
is not where the money is.

Three savings, in descending size:

1. **Research fit per university, not per programme.** It searches *the university's domain*
   for *the student's topic* and never reads the programme, so two programmes at one university
   compute an identical answer twice. The week-long reuse cache is keyed per programme; keying
   it per institution is a pure deletion of duplicate work, with **no quality change**.
2. **Public page text cached across students**, keyed by URL alone. A university's page is the
   same for everyone. Today the cache is per tenant. One cost, stated: a cache hit is faster
   than a miss, so one agency could in principle infer that another had fetched the same
   university. Public pages, no student data, and the alternative is paying for the same bytes
   once per tenant.
3. **The story once per reader kind** instead of once per programme.

**Jev** takes the two highest-volume judgements — the sentence classifier (one call per page)
and the written-requirement check (up to six per letter). Both are "score this against fixed
criteria", which is its shape. Owner decision: **no frontier-model fallback.**

## 6. Failure handling

The classifier already degrades correctly: unavailable means no candidate, which ends as "no
match found" — honest, and research fit never blocks a letter (D11).

The requirement check does **not**, and this design fixes it. Today, if every reading is lost,
nothing is reported, because the check "can only ever add evidence, never manufacture it" —
correct with three readings from two vendors, wrong with one judge, because an outage then ships
every letter unchecked and looks identical to checked-and-fine. **No reading at all becomes a
recorded flag on the draft.** The letter still goes out, because nothing may block a student's
pack; "not checked" is written down instead of being silent.

## 7. The rate limit must move

**Two** limiters stand in the way, not one. Letter generation is 20 per student per hour, so a
20-programme pack hits it exactly and a larger one fails partway through. Storyline proposal is
10 per student per hour — which is ample for one story per theme kind, but the same-university
rule spends an extra proposal per additional programme at a shared university, so a pack heavy
on one institution can exhaust it while the letter limiter still has room.

**Recommendation: limit the pack, not the letter.** One pack build per student per hour,
replacing both per-call limiters for work done inside a pack build. A pack is the unit of work
the student asked for, so it is the honest thing to count, and it bounds spend better than two
counters that a large pack trips for unrelated reasons. Calls made outside a pack build — the
console command, any later single regeneration — keep their existing limiters.

This is the one item in this design that **weakens** an existing safety limit, so it is called
out for the owner rather than assumed. The cost it admits is bounded and calculable: one pack
build is (theme kinds + extra same-university programmes) storyline proposals, plus one
generation per programme, plus the research-fit and requirement-check calls §5 covers.

## 8. This is two plans, not one

The two halves share a motivation and nothing technical, so they should be planned and shipped
separately:

**Plan A — wiring and scope.** Wire `propose_storylines`/`choose_storyline`/`CORE_NARRATIVE`
into pack generation, add the two columns, the same-university refusal, `cluster_key` losing its
subject, and the rate-limit move. Most of it is assembly; the genuinely new code is
`letter_scope` and the same-university check.

**Plan B — cost and Jev.** The two research-fit cache keys, Jev on the classifier and the
requirement check, and the not-checked flag. Touches no letter structure at all.

**A first**, because it changes stored shapes and B does not, so A landing second would rebase
onto a moving target. B is also the half that is blocked outside our control: Jev's sign-ups are
broken as of 2026-09-24. A does not wait on that.

## 9. Testing

- Each scope value: `PER_PROGRAMME` writes N letters; `SHARED_RANKED` writes one covering N in
  ranked order; `FIRST_CHOICE_ONLY` writes one naming only the first.
- Two programmes at one university never share a story paragraph; two at different universities
  do.
- Two reader kinds in one pack produce two stories.
- Research fit runs once for two programmes at one university (assert the call count, not the
  result).
- A requirement check with every reading lost writes the flag and does not block.
- `cluster_key` takes no subject argument (pins the deletion).
- An immigration or consortium prompt still generates with **no** storyline
  (`theme_kind_for` returns None), and `check_storyline_drift` passes. This is existing
  behaviour and the wiring must not break it.
- Two programmes at one university get two DIFFERENT themes, obtained by feeding the used theme
  into `recent_themes` — asserted on the themes, not just on the paragraphs.

Every count assertion counts *calls*, not outputs: this design is about not paying twice, and
an output-shaped assertion passes whether or not the work was duplicated.

## 10. Deliberately not built, with the trigger

- **A letter belonging to several programmes across different universities.** Every
  `SHARED_RANKED` system found scopes its choices to one funder or one university. Trigger: a
  system that ranks courses at different institutions in one letter.
- **Sharing research-fit matches between students.** Only page text is shared. Trigger: the
  recorded outcomes show the same sentence matching many students, and a rule exists for who
  may see whose result.
- **The fee unit.** Recorded in the research, modelled nowhere; it drives no letter logic.
- **Department-level separation.** Nothing records a department. Trigger: a department field.

## 11. The gap this design does not close, and it is larger than this design

Research fit cites what a lab's page says, with no idea when the page was written, and never
looks at publications. A confident citation to a group that changed direction three years ago
is worse than a vague paragraph, and "what this group works on now" lives in recent papers. The
platform already calls OpenAlex and Crossref on the evidence side, so the data is reachable
without a new vendor. **This is a bigger lever on letter quality than everything above**, and it
is named here so that finishing this design is not mistaken for finishing the letter.
