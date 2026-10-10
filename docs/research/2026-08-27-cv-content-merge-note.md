# CV content + tailoring — three-run diff and what it changes

Runs: `2026-08-27-cv-content-claude-run.md` (Claude Deep Research),
`2026-08-27-cv-content-gemini-run.md` (Gemini Deep Research),
`2026-08-27-cv-content-gptr-run.md` (GPT Researcher/Tavily, Track B only).
Prompt: `2026-08-27-cv-content-research-prompt.md`.

## 1. Unanimous across all three — treat as settled

- **Track B's premise is unevidenced.** No study, audit experiment, RCT or admissions
  outcome data anywhere showing a programme-tailored CV beats a strong generic one in
  master's admissions. Three independent runs, three nulls.
- **ATS/keyword screening does not happen in master's admissions.** It is a recruitment
  practice. The Claude run notes the recruitment industry itself debunks the
  "ATS auto-rejects 75%" figure as a claim that sells resume services.
- **No published time-per-file figure exists for European master's admissions.** The
  4-12 minute and two-reader numbers are US undergraduate consultancy claims.
- **Fabrication is binding and enforced.** Manchester, UCL, Bristol, Edinburgh, City,
  UCAS, Charles University, Oxford/Wadham, Cambridge Judge, the Rhodes Trust. Consequences
  run to application cancellation, offer withdrawal and post-enrolment de-registration.
- **No institution anywhere draws a written line between "emphasis" and "fabrication."**
  Policies target falsity and omission; emphasis is left undefined and implicitly permitted.
- **Institutional legibility is an institutional job.** ENIC-NARIC, the Diploma Supplement,
  ECTS, uni-assist's VPD and WES exist to interpret unfamiliar institutions. Offices ask
  for those, not for CV editorialising.
- **Rankings on the CV have no institutional support** in any run.

## 2. The finding that outranks the one we went looking for

Both deep-research runs independently established something stronger than "tailoring is
unevidenced": **in published European rubrics the CV carries close to zero scoring weight.**

| Institution / programme | Mechanism | CV weight |
| --- | --- | --- |
| TUM, MSc Quantum Science & Technology | 120-point aptitude assessment | **0 points** (transcript 40, motivation letter 40) |
| TUM, MSc Biomedical Eng. & Medical Physics | point-based | **0 points** |
| TU Delft, MSc Aerospace Engineering | formulaic ranking | **0%** (exam 60%, academic aptitude 40%) |
| Copenhagen Business School | holistic academic match | absent from published criteria |
| Swedish HEIs (universityadmissions.se) | national merit rating | **0%** — transcripts and credits only |

And a peer-reviewed source agrees: Kurysheva, van Rijen, Stolte & Dilaver, *Int. J. STEM
Education* 10(1), 2023, DOI 10.1186/s40594-023-00445-4 — a mapping review placing the CV
among selection methods "not given substantial weight in selection decisions."

The CV is **mandatory to submit, binding in format, and near-weightless in scoring.**

## 3. Where the runs genuinely disagree — and why both are right

### 3a. Is reordering/selecting legitimate tailoring, or prohibited?

- **Claude run:** reordering and selecting are the two *defensible* tailoring operations,
  supported by Sciences Po, which states the CV "is essential… must be tailored" and
  "should not be a mere chronological listing."
- **Gemini run:** both are **"Folklore / Prohibited"**, because uni-assist, TUM and DAAD
  require gapless CVs — "List everything you have done up until now. Start with your first
  school. Do not leave out any period."

**Both are correct, for different countries.** France requires tailoring; Germany and
Switzerland prohibit the omission that tailoring implies. ETH Zürich demands a continuous
history from secondary school onward, in the language of instruction.

This is not a contradiction in the research. It is a real per-destination conflict, and it
maps exactly onto the COUNTRY and FUNDER scopes `CatalogRule` already has. A resolver that
picks the most specific applicable rule is the right shape for it — which is what shipped
in PR #24.

### 3b. The institution website URL

The question that started this. The three runs split:

- **GPTR run and Claude run:** no primary source recommends it; coaching folklore.
- **Gemini run:** **Charles University (MFDA) explicitly asks for it** — "We ask applicants
  to include sufficient information (preferably a hypertext link) to identify the schools
  where they studied, the organizations they worked for, the competitions they participated
  in, and any other relevant information."

The Gemini finding stands: there is at least one published admissions policy requesting
hyperlinks, and it requests them for precisely the unfamiliar-institution purpose. The
earlier conclusion that it had no primary support was wrong.

It remains destination-specific, not general. R-017 (Fulbright) discourages hyperlinks;
Charles University asks for them. Another COUNTRY/FUNDER-scoped rule, not a default.

Charles University also formally welcomes "information on the relative performance of an
applicant in his or her cohort (i.e. GPA percentile)" — supporting class-rank/percentile,
which `EducationEntry` does not yet carry.

## 4. Source-quality caveat on the Gemini run

Its findings are valuable and several are unique to it, but its citations are weaker than
its tiering claims. Before any of these enter the catalog they need re-verification against
a primary domain:

- **C-005, C-006, C-009, C-010** (Charles University MFDA) all cite a **scribd.com** upload,
  not a Charles University domain. The claims are probably sound; the provenance is not.
- **C-014** (APS certificate for Indian applicants) cites **leapscholar.com/blog**, a
  study-abroad agency, while labelled "Published policy (Tier 1)". That is a mis-tier.
- The Europass XML schema claims cite **slideshare** and **scribd**, not the EU's own
  documentation.
- The TU Delft selection figures cite **delftprep.nl**, a commercial prep service.

The Claude run's citations are cleaner throughout — university domains, a DOI for the
peer-reviewed source, official DAAD and uni-assist PDFs. Where the two conflict on a fact
rather than a jurisdiction, prefer the Claude run's sourcing.

## 5. What this changes for the product

1. **The CV is a compliance document, not a persuasion document.** The value is in not
   being excluded — gapless where required, tabular where required, within page limits,
   in the right language, with nothing unverifiable. That is exactly what the `CatalogRule`
   engine does. The rule catalog is the evidenced product; "CV maximisation" is not.
2. **Tailoring stays a product bet, not an evidenced feature.** Build it if you want it,
   but do not claim evidence, and cap the effort. Never let it introduce a claim the
   applicant cannot document.
3. **Omission is dangerous, not clever.** In Germany and Switzerland, dropping an entry to
   make room is a rule violation, and DAAD treats a missing document as grounds for
   exclusion. Any "select the best N entries" logic must be country-aware or it will
   actively harm German applications.
4. **Evidence intake (subsystem 1) survives untouched and gets stronger.** Both runs
   converge on verifiability as the high-value check — the Claude run's Stage 4 is
   "the counselor's highest-value check is not polish but verifiability: every claim must
   be corroborated by transcript, certificate, publication or reference." Extracting real,
   documented facts from a repo or a publication serves that directly.
5. **Generic soft skills are inert, not harmful.** Both runs land there. The CGS study
   found critical/analytical thinking *are* valued attributes but are assessed through
   references, statements and interviews — not a CV list. So listing them neither helps nor
   hurts. No reason to refuse them; no reason to promise they do anything.
6. **New schema gap:** class rank / cohort percentile. Charles University asks for it and
   US credential guidance calls it more telling than a converted GPA. `EducationEntry` has
   `grade_native`, `grade_scale` and `grade_conversion` but no rank field.

## 6. Open, and not resolved by any run

- Austria: no primary CV content rule located.
- A granular UK master's rubric: thin in all three runs.
- Whether generic competencies are *ever* penalised: all three infer "inert" from absence
  of evidence, which is an inference, not a measurement.
