# CV style — merged companion note (diff of two deep-research runs)

Product of diffing `2026-08-26-cv-style-claude-run.md` against
`2026-08-26-cv-style-gemini-run.md`. The ruleset is `cv-style-rules.csv`
(S-001..S-024). This note records what the diff showed and what the template
designer owns.

## Where the runs agree (the load-bearing consensus)

Both runs, from largely independent sources, describe the same default object:
single-column, reverse-chronological, education-and-research-first, 10–12pt
standard face, ~1-inch equal margins, name largest and bold, headers
left-aligned bold caps, dates right except in DACH, bullets for experience,
CEFR text for languages, no decoration of any kind. Both also independently
confirm the same two negatives: no admissions-side source prefers serif over
sans (folklore), and style is advisory almost everywhere — binding rules live
in the compliance layer (`cv-rules.csv`), not here.

**Settled by two-run agreement: our GERMAN_TABULAR variant was German in name
only.** Both runs state the tabellarischer Lebenslauf is a strict two-column
grid with dates/labels in the LEFT column. The variant previously rendered
dates right, identical to STANDARD, differing only in the contact block.

## Where they disagree, and the resolutions taken

1. **DACH bindingness.** Gemini marks the tabular form "Binding" citing
   LMU/Heidelberg programme pages; Claude calls it advisory convention.
   Resolution: advisory by default, binding per programme where a programme
   states it — matches the existing enforcement model. Verify the programme
   page before loading any BINDING row (S-008).
2. **Length.** Claude: 1–2 FULL pages (Oxford graduate admissions,
   requirement-level when a CV is required). Gemini: the academic CV is
   uncapped (UToronto/Harvard, faculty-CV framing). Resolution: our audience
   is master's admissions, so 1–2 full pages is the default; uncapped applies
   only where a programme invites a research CV (S-009).
3. **France.** Claude: one page (commercial sources only). Gemini: documented
   gap — no university-primary style page exists. Resolution: recorded as a
   gap with a soft 1-page default, Low-Medium confidence (S-017).
4. **Japan.** Claude researched the rirekisho (domestic employment form);
   Gemini found international master's admissions accept free-format CVs and
   care about file-naming. Complementary, not conflicting; Gemini's framing
   is the relevant one for this product (S-019).

## Ground-rule violations found at merge (why the diff was worth it)

- Gemini's F-pattern row cites TheLadders/resumefast — the recruiter
  "six-second scan" study the prompt explicitly excluded, and which the
  Claude run correctly quarantined. Kept only as reading-conditions
  inference, numbers discarded (S-024).
- Gemini's ERP/eye-tracking neuroscience (P200/N300) and several source URLs
  (academia.edu-hosted Harvard doc, cvcircuit.com, an IU helpsheet attributed
  to BU) are weakly provenanced. Nothing in the merged ruleset rests on them
  alone.
- Both runs re-found compliance rules despite the exclusion list (DAAD
  tabular/3pp, Europass mandates, Chevening's no-CV, PDF-only portals,
  rirekisho-as-form). Dropped at merge — they live in `cv-rules.csv`
  (R-010/R-011/R-012, R-003…, R-013). One file per fact.

### Post-merge addendum (authoritative files received)

The user later supplied the authoritative output files; both raw-run bank files
were replaced from them. The chat-paste transcription of the Claude run had lost
nothing but diacritics; the Gemini paste had LOST its works-cited list (58
sources) and two tables, now restored. The restored citations sharpen the S-008
bindingness caution: Gemini's "Binding" DACH claim rests on one LMU programme
page plus a Heidelberg Erasmus info-evening SLIDE DECK, and its bibliography
contains outright pollution (citation 12 is a linguistics dissertation on
verb aspect). The advisory-by-default resolution stands.

## New since run 1 (Gemini's genuine contributions)

The R4RI narrative-CV watch item (S-021), never-underline (S-006), strict
left-justification (S-016), published-vs-under-review separation folded into
S-011, the Japan reframing (S-019), and ADA University/Azerbaijan explicitly
covered (S-020).

## What falls to taste — the designer owns these

Serif vs sans (pick for legibility; both runs confirm no admissions rule);
exact hierarchy within 14–18pt name / 11pt body; language-block
micro-layout; the French one-pager and Nordic skin (informed guesses until a
primary source appears — labeled so in the CSV).

## Immediate deltas for this repo's templates (evidence-cited)

1. Body 10.5pt → 11pt (S-002); margins 18/16mm → 20mm equal (S-003).
2. Name + page number footer (S-023).
3. GERMAN_TABULAR rebuilt as a real dates-left two-column grid (S-008).
4. Half-empty page 2 is now an evidence-backed careless tell (S-009/S-022) —
   counselor-checklist item; automated widow control is future work.
5. Links/ORCID in the header (S-013) and structured publications (S-011) are
   evidence for the already-queued schema work (links field, bullet
   structure, structured publications).
