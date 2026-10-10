# Parallel research prompt — what actually goes IN a master's CV, and whether tailoring works

Paste the block below into Gemini Deep Research, Claude, or any research agent. It is
self-contained: it assumes no access to this repository. Run it in at least two tools and diff the
outputs — disagreement between them is itself a signal about which claims are solid.

Output merges into `docs/research/cv-content-rules.csv` (same column layout as `cv-rules.csv`) plus
a companion findings note for the empirical questions, which are not rules and must not be forced
into the CSV.

**Why this run exists.** `cv-rules.csv` and `cv-style-rules.csv` cover what a CV must *look like*
and what funders *require*. Neither covers what should be *in* it, or whether adapting it per
programme changes anything. Rule R-050 in the existing catalog already concedes the gap: "all cited
policies are US undergraduate ESSAY policies; no master's/CV-specific." Track B below is the
load-bearing question — a product feature is being sized on its answer.

---

## THE PROMPT

You are doing source-grounded research for a product that prepares **master's-degree application
CVs** for international applicants worldwide — many from countries whose universities a European or
North American admissions committee will not recognise — and then has a human counselor review the
result. Accuracy of sourcing matters far more than completeness.

### Ground rules (apply to everything below)

- **Cite a primary source for every claim.** A university's or funder's own page, official
  application guidance, an official template, an admissions office's published statement, or a
  peer-reviewed study. University careers-service pages are acceptable but must be labelled as
  guidance, not requirement.
- **This topic is saturated with folklore. Treat that as the main hazard.** Recruitment blogs,
  CV-builder marketing, and career-coach content will answer every question below confidently and
  with no evidence whatsoever. Do not launder that into a finding. For every claim, state whether
  the source is (a) a published policy, (b) an admissions professional speaking on the record about
  their own process, (c) an empirical study, or (d) coaching advice. Mark (d) as folklore, and say
  so even when (d) is unanimous — unanimity among coaches is not evidence.
- **Never infer a requirement from an example.** A sample CV showing a field is not a rule that the
  field is expected.
- **Separate binding from advisory.** Binding = stated in writing by the university or funder, with
  ineligibility or rejection as the consequence. Advisory = convention or coaching. When in doubt,
  advisory.
- **Distinguish master's admissions from three adjacent things that do not transfer:** US
  undergraduate admissions, PhD/faculty hiring, and commercial job recruitment. Most published
  material is one of those three. Say explicitly which one a source is, and do not carry it over
  without saying why it transfers.
- **A null result is a result.** "No published evidence found" is the single most useful answer
  this research can return for Track B. Do not fill a gap with plausible-sounding general advice.
  If the honest state of the evidence is that nobody has measured this, say that plainly.
- Note the date and application cycle each source refers to.

---

### TRACK A — How a master's admissions committee actually reads a CV

**A1. Does the CV carry weight at all?** For master's admissions specifically, where does the CV
sit relative to transcript, statement of purpose / motivation letter, references, and test scores?
Find published rubrics, admissions-office descriptions of their own file review, or committee
guidance documents. Cover at minimum: Germany (including uni-assist), the Netherlands, France,
the Nordics, the UK, Switzerland, Austria, and the Erasmus Mundus consortia — and separately the US
and Canada for contrast. Report per-country where the answer differs.

**A2. Who reads it, and for how long?** Is master's admissions file review done by professional
admissions staff, by academic faculty on the programme, by a committee, or by a first-pass
administrative filter? Is there published data on time spent per application at master's level?
Existing US undergraduate figures (4-12 minutes per file, two-reader splits) are known — establish
whether anything comparable is documented for European master's admissions, and if not, say so.

**A3. Is any of it automated?** Do master's admissions systems screen CVs by keyword, ATS-style, or
is that a recruitment-world practice that does not occur in university admissions? This is widely
asserted by CV-builder marketing; look for evidence either way and be explicit if there is none.

**A4. Do reviewers follow hyperlinks?** Anything on the record about admissions readers opening
links in an application document — DOIs, GitHub, portfolios, institutional websites. Distinguish
master's admissions from recruiter behaviour.

---

### TRACK B — Does programme-specific tailoring change outcomes? (PRIMARY QUESTION)

This is the question the run exists for. Answer it honestly even if the answer is "nobody knows."

**B1. Is there any empirical evidence** — study, audit experiment, admissions-office statement,
published outcome data — that a CV adapted to a specific programme performs better than a strong
generic one, in *master's admissions*? Not in job recruitment. If the only evidence is from
recruitment, say so and report what it shows, clearly labelled as non-transferable until shown
otherwise.

**B2. What do admissions offices themselves say?** Do any explicitly ask applicants to tailor the
CV to the programme, or explicitly say it makes no difference? Quote them.

**B3. If tailoring matters, what specifically is being tailored?** Distinguish, with sources:
  - reordering existing material so relevant items appear first
  - selecting which items appear at all when space is constrained
  - rewriting descriptions to use the programme's vocabulary
  - adding skills or claims not otherwise present
Report which of these has support and which is folklore. The fourth is of particular interest: is
there any published guidance for or against adding competencies that are not evidenced elsewhere in
the document?

**B4. What is the risk side?** Any published cases, policies, or admissions statements about CVs
that were tailored to the point of misrepresentation? What is the stated consequence — and does any
institution distinguish "emphasis" from "fabrication" in writing?

---

### TRACK C — Making an unfamiliar institution legible

The applicants here are frequently from Azerbaijan, Central Asia, Pakistan, Türkiye, the Caucasus
and Sub-Saharan Africa, applying to European programmes whose committees will not know their
university.

**C1. What does official guidance say** the applicant should supply so an unknown institution and
grading system can be interpreted? Cover grading scale statement, class rank / percentile, ECTS
equivalence, Bologna alignment, national accreditation status, and credential evaluation (WES,
uni-assist, ENIC-NARIC). Which of these do admissions offices actually ask for, and which are
applicant-side coaching?

**C2. Is the institution's website URL in the education entry ever recommended by a primary
source?** Specifically: does any university, funder, or admissions office suggest it — or is it
purely coaching advice? Note that the Europass CV schema does contain a `website` field on education
entries; establish whether filling it is expected practice in Europass-submitting contexts or simply
an available field.

**C3. Institutional rankings on a CV.** Any primary-source guidance for or against stating your
university's ranking in the education entry. Report honestly if the only support is coaching.

**C4. Coursework.** When, if ever, does official guidance ask for a list of courses or modules on a
master's application CV? Under what conditions is it recommended — e.g. thin research output, career
change, a programme with specific prerequisites — and when does it displace stronger material?

---

### TRACK D — Skills sections

**D1. Generic competencies.** Is there any evidence about listing non-technical competencies —
"critical thinking", "analytical thinking", "teamwork", "communication" — on a master's application
CV? Do admissions readers report finding them useful, ignoring them, or holding them against the
applicant as filler? Distinguish evidence from convention. If the honest answer is that they are
inert — neither helping nor hurting — say that.

**D2. Evidenced vs. declared skills.** Any guidance on whether a skill should be demonstrable from
elsewhere in the document — a project, a publication, a role — rather than merely asserted in a
list? Does any institution or funder address unevidenced skill claims explicitly?

**D3. Self-rated proficiency.** Guidance on proficiency levels for technical skills
("advanced Python"), as distinct from CEFR language levels, which are a separate and standardised
case.

**D4. Programme-specific vocabulary.** If a programme is, say, AI-focused, is there primary-source
support for describing existing work in that programme's terminology — or is this the same folklore
as B3's third bullet?

---

### Output format

Two artefacts.

**1. A rules CSV**, columns exactly:

`ID, Rule, Applies to, Scope, Binding or advisory, Source (tier), Source URL [provenance], Verified for cycle, Confidence`

Only for claims that are genuinely prescriptive. Prefix IDs `C-` for this run so they cannot
collide with the existing `R-` and `S-` sets.

**2. A findings note (prose)** for everything empirical rather than prescriptive — Track A2, A3, and
all of Track B. These are not rules and must not be forced into the CSV.

End the note with an explicit **evidence-quality verdict**: for each of Tracks A, B, C and D, state
whether the conclusions rest on published policy, on-the-record admissions practice, empirical
study, or coaching folklore — and name the weakest link in each. If Track B's honest answer is that
the premise is unevidenced, lead the note with that sentence.
