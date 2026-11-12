# What the student wants to study — matching, narrowing, and the funder's level

**Status:** design approved in conversation 2026-10-14 (owner, two rounds of choices); this file
awaits the owner's review before a plan is written. It **amends** the tailored-programme spec
(`2026-09-25-tailored-programme-finding-design.md` §3.2, §3.3, §4.2) and the funding-engine master
spec (`2026-09-22-funding-search-engine-master-design.md` §6.4a and the query-words table in §10.5).
Where they disagree with this file, this file wins.

## 1. Owner decisions recorded here (2026-10-14)

| # | Decision |
|---|---|
| F1 | A student who is unsure narrows in steps, and **every step offers "I don't know"**. "I don't know" means everything under that step is acceptable: the list stays wide there and mixed across the branches. |
| F2 | Two kinds of narrowing step: **subject** (organic, materials, computational …) and **way of working** (lab, computational, theory). They are different questions: synthesis or computation runs across every branch of chemistry. |
| F3 | **Research vs industry focus is read from the programme's pages, not asked by default.** Question 7 (PhD / work there / return home) sets the default lean; it is asked as a narrowing step only when question 7 gives no lean and the found programmes differ on it. |
| F4 | **The counsellor is an AI. No person is involved anywhere the student is.** Back-office checks on the shared catalogue (the `ResolutionItem` queue, the hold queue, confirming an unknown institution) stay, because they protect every student from bad data. |
| F5 | A **"Something else"** answer exists at every step: one short typed answer, read like the first description. Not an open chat (T3 stands). |
| F6 | What the student types is **matched to known subjects and confirmed** ("We understood: …"). DeepSeek may **suggest** other names and subfields; only suggestions that exist in an open subject list are kept. |
| F7 | **Measure before building labels**: ~50 programme pages in 5 countries, for module lists, credits and focus signals. |
| F8 | Search **neighbouring fields** when the programmes found point there, **at most 2 per student**. |
| F9 | **The only funder level that counts is master's.** A funder is shown when its page says it funds master's students, dropped when its page says it does not, and sent to Elmify staff when the page does not say; staff record yes or no. |
| F10 | Removing "master's" from the funder search sentences (commit `07a196dd`, branch `claude/kind-vocabulary-adapter`) is re-checked in **Japan, South Korea and Russia** once F9 is built. |

## 2. Why no standard subject list is the label (checked 2026-10-14)

| List | Size | Chemoinformatics | Bioinformatics | Computational chemistry |
|---|---|---|---|---|
| UNESCO ISCED-F 2013 (the EU's) | ~80 detailed fields | absent | absent | absent (its one "informatics" is computer science, 0613) |
| US CIP 2020 | 2,325 programme codes | `40.0512` | `26.1103` | folded into `40.0512` as an example |
| OpenAlex Topics | ~4,500 | folded into "Computational Drug Discovery Methods", under **Computer Science** | spread over topics under Molecular Biology | absent |
| OpenAlex Keywords | 1,881,745 | present, alternatives incl. "chemoinformatics", Wikidata `Q910164` | present | present |
| UK HECoS | 1,092, flat | not confirmed (site refused) | `100869` | not confirmed |

So every list either lacks these fields or folds them into a broader or wrong term, and the one that
has them (OpenAlex Keywords) is too fine to show a student (it lists "RDKit") and is English-only.
**Labels are therefore the programme's own words (T6, T7 unchanged); lists only place a label and
give its names in other languages.** Wikidata's item for cheminformatics carries ~45 language names
(`Chemoinformatik`, `chémoinformatique`, `化学信息学`, `kemoinformatika` …), which is what a search
in each country needs.

## 3. From what the student types to search words

Example: *"I want to study AI for chemistry"*.

1. **Candidates, from lists.** OpenAlex's text tagger (`GET /text?title=`) and its keyword search.
   Measured 2026-10-14: on the English sentence the tagger returned *artificial intelligence*,
   *chemistry*, *machine learning*; on the Turkish one (*"kimya alanında yapay zeka okumak
   istiyorum"*) it returned *machine learning in chemistry* — but both times its main topic was the
   wrong one (*Machine Learning in Materials Science*). Keyword search finds *machine learning in
   chemistry* with six alternative names once the words are right. Wikidata's name search finds
   nothing from a sentence. So lists alone are not enough, and a model alone may invent.
2. **DeepSeek proposes** (`SWEEP_ANGLE_MODEL`, one call, about $0.001): the field, a focus within it,
   other names, and 3–6 nearby subfields, as a schema. Reference pattern: the typed text is DATA,
   `extra="forbid"`, capped output, `store=False`, a per-student `rate_limited`.
3. **Only what a list confirms is kept.** Each proposal is looked up in OpenAlex Keywords and
   Wikidata; a proposal found in neither is dropped and counted. This is what keeps general
   knowledge from becoming a match (T7): the model widens the net, the lists decide what is real.
4. **The student confirms** one screen — *We understood: Chemistry → AI / machine learning in
   chemistry (also called cheminformatics)* — with *Yes*, *Close — let me pick* (3–4 nearby
   subjects) and *Something else*.
5. **Stored**, per profile version: the student's own words; the confirmed subjects (Wikidata QID
   and/or OpenAlex keyword id); the kept alternatives; every narrowing answer, with "I don't know"
   stored as its own value (asked and left open), distinct from "not asked". The existing
   `research_interests` profile field — which `tap_query.py` already reads but no intake question
   fills — is filled from the confirmed focus and the narrowing answers.
6. **Search words**: the confirmed subjects' Wikidata names in each search language, their OpenAlex
   alternative names (English), and the student's own words. The **top 2–3** alternatives become
   extra angles to start (owner 2026-10-14: more spend is acceptable; raise the number when the
   per-angle tally shows extra alternatives finding programmes the first ones did not); the rest are used only to recognise programmes already found, which costs nothing.
   Cost: one extra angle is about $0.012 per Exa search, so 3 alternatives in 6 languages is about
   $0.20 per student once, inside the $50 cycle wallet, and shared through the cell cache.
7. **Nothing matches:** the student's own words are searched as typed and the record is marked
   `unmatched`, so how often it happens is visible.

`profile_cells.py` is unchanged: it still sorts the student into a coarse discipline bucket for
coverage counting and never enters a query.

## 4. What each programme carries

Read once per programme at ingestion and reused for every student; every label quotes the sentence
or module it came from.

- **Subject labels** in the programme's own words, weighted by credits where the page gives them.
  Each is linked, where one exists, to a Wikidata item and to **one or more** broad parents — a
  chemoinformatics label sits under both Chemistry and Computing. **A label with no entry anywhere**
  keeps its own words and quote, sits under the programme's own department or faculty, still matches
  a student by its words, and becomes a narrowing option once **3** found programmes share it
  (before that it appears under "other areas"). Never dropped, never forced into a wrong term.
- **Way of working**: share of lab, computational and theory modules.
- **Orientation**: research-leaning, in between, industry-leaning, or unclear — from thesis credits,
  a compulsory internship, industry projects, a stated route to a PhD, and the institution type
  (taken from the national registers where they distinguish it: Universität vs Hochschule, WO vs
  HBO, French research/professional tracks).
- **Thin**: pages that list no modules. Shown, never ranked on subject alone. Where the module list
  is one link away (handbook, study plan PDF), it is read there.

**Gate (F7), measured 2026-10-14** on 50 programmes, 10 each in Germany, the Netherlands, France,
Japan and Türkiye (`~/agent-workspace/elmify-runs/field-ladder-measure-2026-10-14/programme_pages.md`,
read with in-session tools):

| | count of 50 |
|---|---|
| module list on the programme page / one link away / only in a PDF / not found | 18 / 11 / 4 / 17 |
| module list readable (PDFs were not, with those tools) | 29 (DE 6, NL 8, FR 8, JP 4, TR 3) |
| credits per module | 17 |
| usable for credit-weighted topics (modules + per-module credits) | 16 |
| orientation decidable | 46 (research 14, in between 19, industry 13; unclear 4) |

What it changes:
- **Credit weights cannot be the main mechanism** (a third of programmes). Labels are unweighted by
  default; credits weight them only where every module has credits. The thesis is 0 credits in
  Japanese and Turkish national credits (Waseda, Sophia, METU) and 25–50% in Europe, so a credit
  weight would erase it there: the thesis is recorded as its own fact, never weighed.
- **PDF module handbooks must be read**: the vendor path reads a PDF as its text (`CLAUDE.md`, Web
  fetching), which the in-session tools could not. "Not found" (34%) is an upper bound: several
  programmes were followed one link or none.
- **A programme with no module list** is labelled from its own description and title, marked thin.
- **Orientation**: 22 of 46 verdicts came from the programme describing itself ("research-oriented",
  "applied master (HBO)"), 14 from career statements, 8 from structure, 2 from who it admits.
  "In between" is the largest group because many pages promise both; structural evidence (thesis
  size, compulsory internship) is weighed above self-description so the label does not drift to
  the middle. Institution type agreed where it exists (all 3 Dutch HBO and 2 of 3 German HAW
  programmes came out industry-leaning).
- **Pages lie or lag**: a programme DAAD lists whose own site says applications are paused, a
  computing page "under construction", an MBA page naming the wrong degree. The programme's own
  page outranks any catalogue, and a paused programme is not offered.

## 5. Narrowing, after the first wide search

1. The search runs wide at the level the student confirmed. Each answer re-sorts and trims the list
   the student already sees; a branch that turns out thin gets one targeted search, whose results
   serve later students in that cell.
2. **Code picks the question**: the label that splits the found programmes most evenly. A step where
   every programme looks the same is skipped. At most **3** steps.
3. **The AI words it**: the question and one line per option, written once per label and language
   and reused for every student — one text that can be checked, not a fresh one per student.
4. Every step offers **"I don't know"** (stop narrowing here, keep the list mixed) and **"Something
   else"** (one typed answer, matched as in §3, starting a search for that branch).
5. **Orientation** (F3) defaults from question 7 and is asked only when it gives no lean and the
   found programmes differ. The list always keeps some of each.
6. **Neighbours** (F8): when found programmes carry labels with a second parent (chemistry →
   computing), one search per neighbouring field, at most 2 per student.
7. Transcript courses, labelled with the same links, **highlight** options; they never answer.

## 6. The AI counsellor, with no person to fall back on

- **Choosing**: code, from the labels (§5.2). The AI never adds an option no programme backs.
- **Explaining**: cached one-line texts (§5.3).
- **Admitting uncertainty**: "unclear" and "the page doesn't say" are values the AI must show; it
  never fills them from general knowledge.
- **Failure** (rate-limited, refused, off-schema): the student gets the wider list and a plain "we
  couldn't narrow this further" note; label words are shown without explanations. Nothing waits for
  a person.

## 7. The funder's level (F9) — owed before any sweep runs level-free sentences

Today nothing records which level an award funds: `apps/funding/grouping.py::_levels_agree` returns
True for an award with no levels, and no reader fills `funding_card["degree_levels"]` (checked on
`master` and every card-reader branch, 2026-10-14). Since `07a196dd` the sentences no longer narrow
to master's, so this check is now the only one.

- **Reader — owned by the card reader, not built here.** The card reader on the unpushed branch
  `claude/card-reader-funding` already reads `target_level` (`card_funding/questions.py`: master,
  bachelor, phd, postdoc, any, year_of_study, not_stated), separately from `prior_degree`. It is the
  only level reader in the codebase, so this spec adds no second one (owner, 2026-10-14). The split
  was sent to that session the same day. Required of it: `master` or `any` (a funder covering
  bachelor's and master's counts) is a yes; other levels only is a no; the application form or the
  rules document one link away is read before answering `not_stated` (cebi's level was only in its
  form); "university / higher-education students in general" is kept apart from `not_stated` until
  the owner rules on it.
- **Serving**: only a yes is shown to a student; a no is dropped; `not_stated` is never shown until
  decided.
- **Staff review**: `not_stated` files a `ResolutionItem` of a new kind, `AWARD_LEVEL_UNSTATED`, asking
  *"Does this award fund master's students?"* — yes / no / I don't know (parks it) — with the page
  quote as evidence. The decision is bound to the page version, as `funding_review` decisions are.
- **Grouping**: `_levels_agree` stops treating "no level" as a match once the field exists.
- **Then (F10)**: repeat the 2026-10-14 Turkish check in Japan, South Korea and Russia, about $5 each.

## 8. What this replaces in the other two specs

- Master spec §6.4a, "Field enters in the page's language — ISCED-F labels per language from
  Wikidata": field words are now the **confirmed subjects' Wikidata names** (§3.6).
- Master spec §6.4a, "Field is a tag, not a query … ISCED-F-derived `tags`": the match key is the
  programme's **own-word labels with their links** (§4). ISCED-F stays only as a coarse grouping.
- Tailored spec §3.3: narrowing is the step sequence in §5, with "I don't know" and "Something else".
- Tailored spec §4.2: vocabulary is §2–§4 of this file; "check OpenAlex Topics as the base
  vocabulary" is answered — Topics folds niche fields away; Keywords and Wikidata are the links.

## 9. Order of work

1. Measurement (F7), running 2026-10-14 — fills §4's gate.
2. Funder level (§7): reader field + `ResolutionItem` kind + grouping rule; then the three-country
   check. Blocks any sweep with the level-free sentences.
3. Subject matching (§3).
4. Programme labels (§4), shaped by step 1's numbers.
5. Narrowing (§5) and the counsellor rules (§6).

## 10. Open

- The "3 programmes share it" threshold (§4) and "3 steps" cap (§5) are first guesses, to be set
  from the first real slices.
- HECoS coverage of chemoinformatics was not confirmed.
- Whether question 7 is a good enough default for orientation is unmeasured.
