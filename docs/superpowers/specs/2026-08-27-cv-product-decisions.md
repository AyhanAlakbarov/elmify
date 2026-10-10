# CV product decisions — decided 2026-08-27

Same purpose as `2026-08-25-application-automation-decisions-design.md`: these bind work that has
not started, which is exactly why they are written down. Every one was decided by the product
owner against the evidence in `docs/research/2026-08-27-cv-content-merge-note.md`, not inferred.

The research is recorded separately and says what the evidence says. **This file says what was
decided, including where the decision runs against the evidence.** A future session reading only
the merge note would find "build it if you want it" and not know the answer.

---

## 1. CV tailoring is being built, as an explicit product bet

**Decision:** build it. "Although it says 0 weight let's tailor it to make it for our clients to
stand out and be the best."

**What the evidence says.** Three independent research runs found no study, audit experiment or
admissions-outcome data showing a programme-tailored CV beats a strong generic one in master's
admissions. Worse for the premise, two runs found the CV scores close to zero in published
European rubrics: TUM MSc Quantum Science gives it 0 of 120 points against 40 for the transcript
and 40 for the motivation letter; TU Delft Aerospace 0%; Copenhagen Business School omits it from
the published criteria entirely; and a peer-reviewed mapping review (Kurysheva et al., *Int. J.
STEM Education* 10(1) 2023) places the CV among methods "not given substantial weight in selection
decisions."

**Why this is not simply overruling the evidence.** The question is *unstudied*, not refuted.
Nobody has measured it. Absence of evidence here is genuinely absence of evidence.

**What binds the build.** Do not claim evidence for it in product copy or internal argument. Cap
the effort. And it is constrained by a rule that is *not* a preference:

> **Tailoring may reorder, compress and rewrite. It may never omit.** uni-assist requires a CV
> "without any omissions… Do not leave out any period". ETH Zürich requires a gapless history from
> secondary school. DAAD requires tabular form and treats a missing document as grounds for
> exclusion. Meanwhile R-023/R-024 cap the page count. So for a German-bound application,
> everything must be listed *and* fit — which is compression, not selection.

France is the opposite case: Sciences Po states the CV "must be tailored" and "should not be a
mere chronological listing". **This is a real per-country conflict, not a research error**, and it
maps onto the COUNTRY and FUNDER scopes `CatalogRule` already has.

**Consequence for code:** any future "keep the best N entries" logic must be country-aware.
`apps/documents/entry_selection.py::select_best_entries` already exists and drops entries beyond a
limit; today it is called only by `funder_templates/sisgp.py`, where SISGP's own template mandates
the cap. **Keep it that way.** A general caller would silently break German applications.

## 2. Generic soft skills are acceptable

**Decision:** listing "critical thinking", "analytical thinking" and similar is fine. "Adding
general skills like critical thinking and other that everyone adds is OK."

**This corrected an error on my side.** I had argued such skills were fraud-adjacent by analogy to
hallucinated achievements. That conflated two different things: "increased training speed 60x" is
a verifiable achievement claim, and "critical thinking" is a conventional self-assessment nobody
reads as evidence. The fraud policies in the research target falsity and omission, not skills
sections.

**What the evidence adds.** Both deep runs land on *inert* — the CGS study finds critical and
analytical thinking are valued attributes, but assessed through references, statements and
interviews rather than a CV list. And the project's own `cv-style-rules.csv` says nothing against
them; S-015 bans skill *graphics*, not skills. So: no reason to refuse them, and no reason to
promise they do anything.

**Programme-specific skills are a different case** and were decided as evidence-driven: "if the
program is about AI then we should analyze what kind of courses maybe a student had, what project
did and write." That is surfacing what the student can evidence, not asserting what he cannot.

## 3. Fabrication is the student's responsibility

**Decision:** "A student can fabricate, it's his responsibility, not ours. We can just advise him
that fabrication can lead to consequences but checking the fabrication is not our responsibility."

**Accepted, with one distinction that shaped the architecture.** The platform does not fact-check
students and could not: nothing can tell us whether he really led a team. But the risk splits:

- **The student overstates his role** — his application, his signature, his consequence.
- **An LLM writes a claim he never made** — that is a platform defect. He signs it without noticing
  it was never his, and the agency using this white-label product wears the outcome.

So the property kept is not *"is this true"* but *"did this come from him or from us."* That is
provenance, not verification, and `VerifiedFact` already models it. The only thing the platform
refuses to ship is **a sentence with no author**. See
`docs/superpowers/specs/2026-08-27-evidence-intake-design.md` for how the tiers implement this.

**The advisory is a real feature, not a disclaimer.** The research supplies the citations to show a
student at the moment he writes a claim: Manchester and UCL (application cancelled, offer withdrawn,
no right of appeal), UCL again (de-registration after enrolment), Cambridge Judge, Charles
University (automatic disqualification), the Rhodes Trust (monitors for "embellishments and
inaccuracies").

## 4. Priority order, and the shelved letter engine

**Decision:** finish the CV engine first. Evidence intake is the first subsystem specced.

**What the research implies about everything after that.** The motivation letter is the document
that scores — 40 of 120 at TUM, with **20 of those points for "discussion of your qualification
with respect to the programme requirements"**. That is programme-specific tailoring with a
published point value, in the letter rather than the CV. Every admissions office in the research
mandates tailoring *of the letter*; not one asks for it in the CV.

**`claude/phase2-motivation-letter-engine` has 59 commits and no PR** — `letter_ai_policy.py`,
`letter_gates.py`, `letter_verification.py`, `letter_render.py`, `letter_schemas.py` and more. It
has never been compiled against weasyprint 69 or mypy 2.3.1. It reads the same `VerifiedFact`
ledger, so evidence intake feeds it directly.

**Standing recommendation, not a decision:** the highest-value unstarted work is reviving that
branch. It was noted and deferred, not rejected.

## 5. Settled implementation choices

Recorded so they are not relitigated:

- **Repository reading uses the host REST API, never a clone** (option C). Every tool in the
  repomix/gitingest/code2prompt family clones; they solve file-walking, which is cheap, and not
  connecting to a host the student named, which is not. See
  `docs/research/2026-08-27-evidence-intake-landscape.md`.
- **GitHub and GitLab only.** Private GitHub via a fine-grained PAT scoped to one repository,
  read-only. **Private GitLab is out of scope** — gitlab.com puts project access tokens behind
  Premium, deploy tokens are git rather than API credentials, and a `read_api` personal token is
  scoped to everything the student can see.
- **No credential is ever persisted.** Intake is one-shot: facts persist, access does not.
- **Publications come from Crossref, then OpenAlex.** No library — both are one GET.
- **Which author the applicant is, is never matched by name.** `PublicationEntry.self_author_index`
  exists because "Abdullayev O." and a co-author's similar surname are indistinguishable.

## Still open

Four of the six items below were closed on 2026-08-31; they are kept, struck through, because
what was decided and why is the point of this file.

- ~~**The AI-use policy gate**~~ — closed. It is a catalog rule, not a gate: `ai_use_policy` rows
  seeded ADVISORY_HIGH_RISK for Cambridge, Oxford, Edinburgh, Chevening, Rhodes and DAAD, reported
  to the human approving the draft and never blocking a render. That follows the letter engine's
  own decision (`letter_ai_policy.py`: "never a generation or approval gate"). Cambridge's is the
  one published rule that names the CV outright and is a *university's*, so `CatalogRule` gained an
  INSTITUTION scope between COUNTRY and FUNDER.
- **The rest of the `C-` rules are still not merged into the catalog.** C-002 (uni-assist, "do not
  leave out any period") is seeded as a COUNTRY rule with a `no_unexplained_gaps` checker. C-02
  (ETH gapless) is not: it is one university's rule and COUNTRY CH would apply it to every Swiss
  programme — the INSTITUTION scope now exists to hold it, and it can be seeded once ETH's
  `Institution.canonical_key` is in the catalog. Several other Gemini-run rules cite scribd
  uploads, a study-abroad agency blog and a commercial prep service while labelled "Published
  policy (Tier 1)"; they need re-verification against a primary domain first.
- **ESCO** was deferred in `2026-08-22-open-source-landscape.md` because nothing needed skill
  normalisation. Skills ARE a CV feature now — `tailor_skills` is wired into generation — so this
  is live: matching is case-folded name equality plus a model judging the remainder, and a
  normaliser is the obvious thing to try when that proves too blunt.
- ~~**Class rank / cohort percentile**~~ — closed. `EducationEntry.class_rank`, a string, because
  what a transcript states is a rank, a percentile or a decile depending on the country.
- ~~**Nothing maps `country_code == "DE"` to the `GERMAN_TABULAR` render variant**~~ — closed.
  `select_render_variant` maps DE and AT (S-008's DACH, minus trilingual Switzerland) to the
  tabular variant, but only where the requirement resolves to STANDARD: a published funder format
  outranks a country convention.
- ~~**Priority: finish the CV engine first**~~ — done, in the sense that every part of it now
  reaches a rendered CV. The letter engine (`claude/phase2-motivation-letter-engine`, 59 commits,
  no PR, never compiled against weasyprint 69 or mypy 2.3.1) is next, and §4's reasoning for it is
  unchanged: the letter is the document that scores.
