# Every CV section, every field, against the sources

Audit date 2026-09-15. Baseline: `CVContent` as committed at `ab79a65`, the rendered
STANDARD variant, and `docs/research/cv-rules.csv` (93) + `cv-style-rules.csv` (41 after this pass).

Evidence gathered this session, non-US weighted as instructed: University College Cork's
PhD/postdoc CV guide (per-section table **and** two full worked CVs), Newcastle's academic
CV workbook, University of Toronto's *Creating your academic CV for Masters and PhDs*
(four worked samples), University of Queensland's graduate-school guidelines, Oxford
Careers, Utrecht, UC Berkeley, UPenn, CU Boulder.

---

## The finding that governs every other one

**Almost everything I collected is faculty-CV inventory, and our applicant is applying to
a master's.** UCC's guide is for "PhD and Postdoctoral Researchers". Newcastle's workbook,
UQ's guidelines, Berkeley's and UPenn's lists and jobs.ac.uk's template are all written for
an academic job search. Toronto's is the only one that says "for Masters and PhDs" on the
cover.

The two sources actually addressed to our audience are much shorter:

- **Oxford** gives a master's/graduate applicant **three** headings: Education (with awards
  nested under the degree that earned them), Experience ("rather than 'Employment'" —
  explicitly including voluntary work and student-society roles), and Interests or Community
  Activity and Skills.
- **Utrecht**: "education and qualifications, work experience, extra-curricular activities
  and interests, additional information, skills and referees."

Against S-009 (1–2 **full** pages for a master's), that matters: the union of every heading
in the faculty guides is around eighteen, and a master's applicant with four research posts
and two papers cannot fill eighteen headings without padding — which S-022 says reviewers
cull on. So the answer to "should we add the sections I saw online" is **two of them, not
seven**, and the reasoning below is about which two.

---

## Section by section

### 1. Contact header — `PersonalInformation`

Have: `full_name`, `email`, `phone`, `photo_url`, `date_of_birth`, `sex`, `citizenship`,
`orcid`, `linkedin_url`, `github_url`, `website_url`, `github_username`, `linkedin_handle`.

Satisfied: S-005 (name largest, contact plain below), S-013 (ORCID and handles in the
header), S-031 (in the body flow, not a page header).

| Gap | Evidence | Verdict |
|---|---|---|
| No Google Scholar field | S-013 names "Scholar" by name | **No change, and the codebase already argued this better than I did.** `website_url`'s own comment: "A Scholar profile, ResearchGate, or a personal page are all just a URL and land here; there is one field rather than one per platform **until a CV needs two of them at once**." That is a stated trigger, and no CV measured has met it |
| No postal address | UCC: "Use your home address if possible or reliable alternative." Oxford: "You **don't** need to include … Home address" | **Leave out.** Two universities directly contradict each other and Oxford is the one writing for our audience. But note R-065: Australia Awards mandates *three* addresses, so the funder-template path will need it |
| Nationality | UCC: "include permanent email, phone number and nationality and/or work authorisation". Oxford: omit unless it shows right to work | **No change.** `citizenship` exists and is off by default, which is R-032's rule and the right default |

### 2. Summary — `summary: str | None`

R-084 (Europass "About Me" is real), R-085/R-086 (objectives belong in the statement of
purpose, and "include a job objective" is employment advice that does not transfer).
UQ calls the same thing "Professional summary or career objective".

**No change.** The field exists, generation refuses to write one without a confirmed
personal fact, and that gate is right.

### 3. Education — `EducationEntry`

Have: `degree_as_awarded`, `degree_english`, `institution_original`, `institution_english`,
`city`, `country`, `start_date`, `end_date`, `grade_native`, `grade_scale`,
`grade_conversion`, `ects_credits`, `thesis_title`, `class_rank`.

Satisfied: R-034 (original + English), R-036/S-027 (native scale, no silent conversion),
R-038 (ECTS), S-037(a) (thesis under the degree, labelled).

| Gap | Evidence | Verdict |
|---|---|---|
| **No supervisor** | UCC: "Include dates, qualification, **supervisor**, dissertation, papers and awards." Toronto sample 4 prints `Dissertation: …` then `Supervisor: Dr. Carine Mendelsson` | **Add.** We already print the thesis and have no way to print who supervised it, and S-037 calls the supervisor the strongest single signal on an academic CV |
| **No funding line** | UCC's worked CV prints `Funded by the Irish Research Council for Humanities and Social Sciences` as a line of the degree | **Add `funding`.** Also closes half of S-037(b) |
| **No relevant coursework** | S-029 (the discipline-switcher's main lever) and **R-028, our own catalog rule**: "Little research output: add research-relevant coursework" | **Add.** R-028 has been in the catalog with nothing able to satisfy it |
| Expected graduation date | R-040, and R-016 (Fulbright requires it) | **No new field.** A future `end_date` already renders; only the "present" wording is ambiguous, and that is a template question |
| Honours classification | S-027 wants it "alongside" the mark; UCC prints it as its own right-hand element | **No change.** `grade_native` carries "16.45/20.0 (Highest Honors)" and splitting it invites a conversion nobody asked for |

### 4. Experience — `ExperienceEntry`

Have: `employer`, `title`, `project`, `supervisor`, `city`, `country`, `start_date`,
`end_date`, `bullets`, `unpaid`.

Satisfied: S-010 (bullets), S-026 (CAR), S-034 (role left, dates right), S-037 (project and
supervisor separate from the role) — `project` landed this session.

**Amended the same day, owner decision: the project is no longer printed.** It is still
extracted, still in the ledger and still an include target — only the standalone line is
gone, so an entry is two header lines and its bullets. Both shapes are attested (S-038), and
the cost was measured before taking it: counting each project title's content words absent
from that entry's own bullets, Groningen lost 0 of 7, EPFL 2 of 5, the Master's Thesis 3 of 7
(including *AZIMUTH*, which appears nowhere else), ICIQ 5 of 5. The bullets "take over" on
one entry in four — necessarily, since bullets are carried verbatim and can only carry the
project if the applicant already wrote it into them. Two things to know: **R-061 binds
Europubhealth+ to print full project names per experience** and renders through this same
partial with no per-field switch to turn it back on; and a *thesis* keeps its sourced home
under the degree in Education (S-037a), which is where AZIMUTH belongs.

| Gap | Evidence | Verdict |
|---|---|---|
| **No lab or group** | S-028: an academic post "names the group or laboratory and its principal investigator". Toronto prints `Department of Industrial Engineering, University of Toronto`; the applicant's own CV wrote `EPFL \| Prof. Schwaller's group` | **Add `group`** — and a `distinct_supervisor` property with it, see below. `employer` holds "EPFL" and the department was lost |

The group field found its own bug on the first live run after it existed. S-028 asks for the
group **and** the investigator because most CVs name a laboratory; this CV names the *person*
— `EPFL | Prof. Philippe Schwaller's group` — so the two fields held one fact and the entry
rendered `Prof. Philippe Schwaller's group, EPFL — Supervisor: Prof. Philippe Schwaller`.
`ExperienceEntry.distinct_supervisor` suppresses the supervisor when the group already names
them, matching on the surname; it is display-only, so `render._section_order` still reads the
raw field and a suppressed supervisor still means this is an academic post. Same shape and
same reason as `PersonalInformation.handles`, which suppresses a handle when the real URL is
on file.
| **`bullets` is required, `min_length=1`** | UCC: an irrelevant role is listed with "name of organization and dates only to account for a possible gap (1 year +). Don't provide detail on irrelevant roles." R-042 and R-011 (DAAD PRIME, gap-free) require the gap to be accounted for | **Conflict, not yet resolved.** A legitimate gap-filler entry cannot be represented. Relaxing to 0 weakens S-010's only mechanical enforcement, so this is a decision, not a cleanup |
| Hours / FTE / duration in months | R-065 (Australia Awards) requires a total-months column and a full-time flag | **Template-local.** Belongs to that funder variant if it is ever built, not to `CVContent` |

### 5. Research — `ResearchEntry`

Have: `thesis_title`, `supervisor`, `institution`, `city`, `country`, `start_date`,
`end_date`, `methods`, `outcomes`. Prose rather than bullets, which S-010 allows for a
specialist reader.

| Gap | Evidence | Verdict |
|---|---|---|
| No funding body | UCC prints the funder on the project line of every research entry | **Add `funding`**, same field name as the education one |

### 6. Publications and Presentations — `PublicationEntry`

Have: `authors`, `self_author_index`, `title`, `venue`, `year`, `volume`, `issue`, `pages`,
`doi`, `status`, `is_presentation`.

Satisfied: S-011 (one style, own name bolded, order preserved, DOI resolvable, published
kept apart from pending), S-030 (presentations are their own section), S-012 (conditional).

| Gap | Evidence | Verdict |
|---|---|---|
| **No URL for an item with no DOI** | The applicant's IAC paper has a landing page and no DOI. `docs/research/…/2026-08-30-generated-cv-review.md` measured that address sitting in the source PDF's link annotations and being discarded; `extract_link_urls` now recovers it, and `PublicationEntry` still cannot hold it | **Add `url`.** Note R-017: Fulbright forbids hyperlinks, so the *renderer* suppresses it there — the field is not the problem |
| Status granularity | UCC lists five states (in preparation / submitted / under consideration / accepted by / forthcoming) against our four | **No change.** "Submitted" and "under consideration" both land in `UNDER_REVIEW`, and nothing downstream distinguishes them |
| Chairing or organising a panel | UCC: "Mention also any experience you have of chairing a session, or organising a panel or conference" | **Not representable, and correctly so.** That is a service activity, not a publication — it belongs to the community/service heading below |

### 7. Awards — `AwardEntry`

Have: `title`, `date`. **This is the thinnest model in the schema relative to what the
sources require, and by some distance.**

UCC, verbatim: "State funding body, terms, duration and amount", e.g. *"IRCSS funded fees
and €12,000 stipend"*; "If award is unfamiliar to the reader, indicate the level of
competition", e.g. *"one of six recipients selected from 3000 applicants"*; "include any
prestigious award offered but not taken up"; "Mention any application that is currently
under consideration". Toronto allows "a brief line below the honour or award name that
explains what the award is for or its primary criteria" and permits the dollar value.
UPenn: "Commonly known honors (Phi Beta Kappa) need no explanation, but other awards can be
briefly explained." Every worked sample prints the granting faculty beside the award name.

| Gap | Verdict |
|---|---|
| **No awarding body** | **Add.** The one field every single source carries |
| **No amount / terms / duration** | **Add one `detail` field**, not four. UCC's own example is a sentence — "IRCSS funded fees and €12,000 stipend" — and four typed fields invite a model to compose one |
| No competition gloss | Same `detail` field covers it |
| No status (offered-but-declined, under consideration) | **Leave.** Both are claims about something that did not happen, and this ledger verifies claims against a document |

Note this also settles the *separate* question of a Funding/Grants heading: UCC keeps one
(its worked CV has a `FUNDING` section listing amounts), UQ calls its heading "Research
grants and relevant awards". Once `AwardEntry` carries a body and an amount, a master's
applicant's two or three items do not justify splitting the heading. **Fix the model, not
the section list.**

### 8. Skills — `SkillEntry`

Have: `name`, `category`, `kind`, `evidence`. S-025 (technical and research-specific only;
transferable skills belong in the bullets that evidence them) is satisfied by `kind`.

S-025 also says "with proficiency indicated" and there is no proficiency field. **No
change recommended**: Berkeley's academic-CV guide carries no skills section at all, and a
self-rated proficiency on a technical skill is the bar-and-dots pattern S-014 bans one
section below.

### 9. Languages — `LanguageEntry`

Have: `language`, `cefr_level`, `test_name`, `test_score`, five sub-skills, `mother_tongue`.
**S-014 is fully satisfied and no source asks for more.** No change.

### 10. References — `ReferenceEntry`

Have: `name`, `position`, `institution`, `email`, `phone`. R-051 satisfied.

| Gap | Evidence | Verdict |
|---|---|---|
| **No "please do not contact" flag** | UCC, verbatim: "For supervisor there is a 'please do not contact' option" | **Add `do_not_contact`.** This is a live instruction about a third party, printed on the document; there is nowhere to put it today |
| Count cap of 10 | UCC: "Two referees is enough – up to four is acceptable" | **No change.** A cap is a ceiling, not a recommendation |

---

## Sections to add: two, not seven

Ranked. The first is the only one with a *binding* rule behind it.

1. **Voluntary / community / civil-society engagement.** Oxford makes it one of three
   headings for our audience; Utrecht lists it; German guidance treats *Ehrenamt* as
   carrying real weight for a university application; and **SISGP mandates it as a literal
   heading** — `NETWORK-CIVIL SOCIETY ENGAGEMENT`, R-064, where altering the category set
   "will render your application ineligible". `ExperienceEntry.unpaid` already exists and
   **only `cv_funder_rhodes.html` reads it**, so on every other variant a volunteering role
   renders indistinguishably from a paid job. This is a render-and-order change over an
   existing field, not a new model — the cheapest item on this list and the best evidenced.

2. **Professional development / certificates / training.** UQ ("Professional development
   activities"), Toronto ("all courses, workshops, certifications, and field specific
   tutorials or qualifying programs"), Berkeley ("Professional Training"), German guidance
   (*Zertifikate und Weiterbildungen*), and master's-specific guidance. Needs a new model
   and a new ledger category, so it is genuinely new work. A summer school currently has
   nowhere to go except Awards, which is where the applicant's own CV put it
   ("Participation in summer school at the University of Strasbourg") — and that is the
   tell.

**Neither depends on the country** (S-042, added after the audit was written). No country
was found whose guidance excludes voluntary or community activity from an admissions CV, and
it is named positively in the UK, the Netherlands, France, Germany, Ireland and the US. What
*is* destination-dependent is the **heading**, and it comes from the funder or the format:
SISGP mandates `NETWORK-CIVIL SOCIETY ENGAGEMENT`, Rhodes calls the same content
`2. Volunteering/Community/Leadership` and routes it by pay rather than subject. Certificates
are sharper still — **Europass has no training section because its education section *is*
"Education and training"**, and SISGP's mandated set uses the same name, so on the two
variants where we have least freedom a separate Certificates heading would be *wrong* and the
content folds into education. Country decides layout (S-008, S-018, S-020); the destination
decides headings, and that already lives in `cv_format_requirement` and `funder_template`.

One fidelity gap found while checking this: `cv_europass.html` overrides only `summary` and
`languages`, so it inherits `cv_base.html`'s `<h2>Education</h2>` and prints EDUCATION where
the Europass editor prints EDUCATION AND TRAINING. R-053 defines our Europass output as a
self-rendered variant matching the editor's sections, so that heading is wrong today — and it
is the heading a certificates feature would have to fold into. Not fixed here: the `<h2>` sits
outside `{% block education_entries %}`, so moving it into a block touches
`cv_german_tabular.html` as well.

Deliberately **not** recommended, with the reason each was rejected:

- **Projects.** R-026 names it in our own taught-track order and it was never built, but
  `ResearchEntry` plus the new `ExperienceEntry.project` now cover it. **Amend R-026**
  rather than add a section.
- **Professional memberships.** UQ, Toronto, UPenn and Berkeley all list it — every one of
  them writing for a faculty job search. A master's applicant has one student-society
  membership, and a heading with one line under it reads as padding (S-022).
- **Teaching as its own heading.** A split of Experience, not a new model. Worth doing only
  for an applicant with real teaching load, which is the research-track case.
- **Research interests.** Overlaps `summary`, and R-085 already routes motivation to the
  statement of purpose.
- **Grants/Funding as its own heading.** Collapses into Awards once `AwardEntry` carries a
  body and an amount — see §7.

---

## What this audit changed, and what it left

Implemented here, nine fields: `EducationEntry.supervisor`, `.funding`,
`.relevant_coursework`; `ExperienceEntry.group`; `ResearchEntry.funding`;
`AwardEntry.awarding_body`, `.detail`; `PublicationEntry.url`;
`ReferenceEntry.do_not_contact`. Every one is optional with a default, so a stored draft
still validates as schema version 3 — the precedent `references` set. Each is also carried
in `_PAYLOAD_KEYS`, without which a CV regenerated from the ledger would silently lose it;
that is the failure `supervisor` had, and one test now covers all nine at once.

`PersonalInformation.scholar_url` was on the list and is **not** implemented: the field it
would duplicate already documents why there is one URL field rather than one per platform,
and gives the condition for splitting.

Left as decisions, because each changes behaviour rather than adding a field:

- the **voluntary/community heading** (§ "Sections to add", item 1);
- a **certificates section** (item 2), which needs a new `VerifiedFact` category;
- **`ExperienceEntry.bullets` `min_length=1`** versus UCC's gap-filler entry (§4).

New catalog rules from this pass: **S-039** (the audience distinction above), **S-040**
(what an education entry carries), **S-041** (the gap-filler entry). **S-035** amended with
UCC's award field list.

---

## Addendum: the Cambridge booklet, read end to end

`https://www.careers.cam.ac.uk/files/cambridgecvsandapplications.pdf` — *CVs &
Applications for Undergraduate & Masters Students*, 43 pages, read in full (every page
carries a text layer; no OCR was needed). Twelve worked CVs, a per-competency evidence
table, a layout chapter, and a chapter on personal statements for Masters courses.

It is a **UK employment** booklet, which is the caveat on everything below — but it is a
university careers service writing for undergraduates and master's students, which is our
audience, and it is the most specific layout source found so far.

**Recorded as S-043 to S-046 and L-072 to L-073.** What it added that the catalog did not
have:

- **Italics are on the same list as underlining.** "Avoid underlining and italics — they
  can make the CV look too fussy and disrupt the flow." S-006 banned underlining only, and
  we render `.gloss` in italic in three places. Live question, not a settled one: S-011
  requires italic journal titles in a citation.
- **Tables are also a readability problem**, not only a parsing one. Third independent
  reason now, two against and one (S-008's DACH mandate) for.
- **Note form, not sentences.** "'I increased the sales' > 'increased sales'." Stronger
  than S-026's active-verb rule, and our real bullets are full sentences with full stops.
- **"Don't use 'Other' in a heading"** — which rules out Queensland's "Other experience"
  by name.
- **The F-pattern and the "dead zone".** S-024 carries the left-loading claim with a health
  warning about contaminated timing figures; Cambridge gives it from a university source
  with no numbers attached — *and* it is the affirmative case for S-007: the date belongs
  on the right **because** the right is the dead zone.
- **"Avoid splitting sections across pages."** We pin the weaker halves (`break-inside`,
  `break-after`); the strong one is unsatisfiable on a two-page CV with four posts.
- **The personal profile, country-scoped:** "In the UK, they are generally unnecessary and
  best left out." That is the source for our `summary` default, which was chosen without one.
- **The gap entry's actual wording — and it supersedes S-041's proposed fix.** Every
  example Cambridge prints has **no employer**: "Intermitted for health reasons (2 terms)",
  "Full-time carer for family member", "3 months' full-time job-hunting". So relaxing
  `bullets` to `min_length=0` would still represent none of them, because `employer` is
  required too. **A gap is a dated statement, not an employment entry**, and needs its own
  shape.
- **"If you exclude grades completely, the reader will probably assume the worst"** — the
  affirmative source for S-027's "expected rather than optional".
- **"Avoid Cambridge jargon like Tripos, Part 1A."** R-034's rule applied to course and
  stage names, not just the degree title — which is exactly an international applicant's
  problem in reverse.
- **Letter side (L-072, L-073):** a six-question structure for a master's statement, a
  25–30 word sentence cap, the "cynical reader" drafting test, and three named failure
  modes with examples — clichés, impersonal statements about the subject, generic praise
  of the university. They are the three a language model writes by default.

### Does the CV differ by discipline? — S-046

**Discipline changes two things, and neither is the one people reach for.**

1. **Which extra headings exist.** Toronto: "there are additional headings that may be
   discipline specific." UPenn: "CVs vary slightly from discipline to discipline."
2. **Citation style and publication ordering.** Toronto: "The manner in which you order and
   present your publications varies from discipline to discipline." That is S-011's
   "discipline-enforced" clause, and **the one place discipline genuinely binds.**

**What does not vary: layout, typography, length, entry shape, core section order.**
Cambridge prints twelve worked CVs across computer science, law, philosophy, social
sciences, journalism and arts, and applies one set of layout rules to all of them. What
differs between its samples is the heading set, tailored to the *target* — "Project
Experience" for the software applicant, "Public Speaking & Debating Experience" for the
would-be barrister. UCC says it in one line: "The presence and sequence of headings will
vary according [to] the experience of the candidate and the nature of the post." Candidate
and post — not subject.

**Searched and not found:** any university source saying a *master's admissions* CV differs
by discipline. Everything asserting a STEM-vs-humanities split — publication share, h-index,
teaching weight, length — is commercial, or about *faculty* hiring, where the humanities
postdoc is often an instructor-of-record and the split is real. It does not carry back to a
two-page admissions CV.

**So yes, we account for it — on the better axis.** `render._section_order` branches on the
**track**, not the subject: `_RESEARCH_SECTIONS` when the CV has research to lead with,
decided from the applicant's own content, while `constraints.resolve_track` separately asks
what programme is being applied to. That is UCC's "experience of the candidate and nature of
the post" almost exactly. An engineer with four supervised posts and two papers needs the
research order; a historian with neither does not — whatever their subjects say.

**The one real discipline-shaped gap: citation style.** `_cv_citation.html` renders one
format for everybody, so the discipline-enforced half of S-011 is unmet. A per-discipline or
per-destination citation variant is the only change this question found worth making.

---

## Addendum 2: the non-UK guides, and what an admissions office actually demands

Read after the Cambridge booklet, on the instruction to look past the UK. Recorded as
**S-047, S-048, S-049**, with **S-043** and **S-046** amended.

### The admissions offices are far more prescriptive than any careers service — S-047

Everything above this line is *advice*. These are **admissions pages**, and they bind.

- **ETH Zurich**: "chronological curriculum vitae **in table form**, leaving nothing out.
  Begin with your **upper secondary school graduation** … **Leave no time gaps: also list
  periods when you did not attend school, study or work** (e.g. longer periods of travel or
  time off)." And: "write the curriculum vitae in the **teaching language** of the desired
  degree programme."
- **TUM** — quantitative where everyone else is advisory: PDF, A4, "Times New Roman or
  Arial", **"12 point"**, margins **"2 centimeters"**, line spacing **"1.5-fold"**,
  "chronological and tabular", month-and-year periods **starting from elementary school**,
  name/surname/**date of birth**, and "**must not contain any gaps longer than 3 months**".
- **Harvard GSD**: "…extra-curricular university activities, community service, honors,
  awards, … avocations, **hobbies**, and travel. … Please provide a complete employment and
  educational history, **including information about any gaps.**"
- **Stanford GSE**: "no page limit, though we typically see resumes of one page with
  12-point font and regular, one-inch margins." **HKS**: several pages is fine.

Four things that settles:

1. **The gap entry is not a style preference.** ETH, TUM, Harvard GSD, DAAD PRIME (R-011)
   and uni-assist (R-020) all require it, and ETH and TUM require periods of *non*-activity
   by name. We cannot represent one — `ExperienceEntry` requires both an employer and a
   bullet. This is now the highest-priority schema gap in the audit.
2. **Tabular is not only DACH.** ETH says table form, TUM says tabular, both at master's
   admission. S-008's bindingness was rated "Medium"; `cv_german_tabular.html` is the right
   renderer for Switzerland too.
3. **Secondary school is destination-dependent, and the camps are flatly opposed.** ETH
   wants upper-secondary onward, TUM wants *elementary* onward; UCC says "typical to omit
   second-level qualifications", Lancaster "isn't necessary to incorporate GCSEs and
   A'levels". No single CV satisfies both.
4. **TUM's typography is not ours.** We render 11pt at line-height 1.3; TUM requires 12pt at
   1.5. A CV rendered today is non-compliant for TUM on two measurable counts, and changing
   the base changes page count for everyone (S-004). Per-destination, not global.

### Harvard GSAS corroborates us from a second continent — S-048

Its 23-page guide restates S-001, S-002, S-003, S-006 and S-007 almost word for word —
"Keep locations, dates and less important information on the **right side** of the page";
"10 to 12 point"; "Margins should be equal on all four sides and be ¾ to 1 inch". Agreement
across continents is evidence, so it is recorded rather than skipped.

It also **settles the italics question S-043 opened**: "Avoid text boxes, underlining, and
shading; **italics may be used in moderation**." Cambridge's blanket avoidance is the
employment reading; our three italic uses are moderate and stay. And it **independently
states the note-form rule** — "Use active verbs and **sentence fragments (not full
sentences)**… Avoid pronouns… minimize articles" — so two universities on two continents
now agree, and our bullets, which are full sentences with full stops, are the outlier.

One more thing worth noting: Harvard prescribes an **"archival CV (for your eyes only!)
that lists all the details of everything you've done — tailor from there"**, which is
Cambridge's "bucket CV" under another name. Two careers services independently prescribe
store-everything-then-tailor. That is structurally the `VerifiedFact` ledger — the
architecture is externally validated, not just internally convenient.

### "Research Intern" — is it the right title? — S-049

**It is a real title, and it is not ours to change.**

Harvard's own sample CVs use five: *Graduate Researcher*, *Research Assistant*, *Graduate
Research Assistant*, *Research Assistant I*, *Undergraduate Research Assistant*. UConn's
undergraduate-research guidance treats *Research Assistant*, *Research Intern* and
*Undergraduate Research Project* as equally acceptable. The rough division: **Research
Assistant** for a post under faculty supervision, **Research Intern** where it was
time-limited — a summer or a semester, which is exactly what EPFL, Groningen and ICIQ were —
and **Undergraduate Researcher** where the status needs stating.

So "Research Intern" is right for those three. The Strasbourg entry is a *Master's Thesis*,
which is not a job title at all — and S-037(a) already says a thesis belongs under the degree
in Education.

**And the architecture already refuses to rewrite it.** `title` is half of the EXPERIENCE
spec's identity in `verification.py` — `identity=("employer", "title")`, the strictest class
of claim. A generated CV that renamed a "Research Intern" to "Research Assistant" would match
no fact in the ledger, come back **UNSUPPORTED**, and block the draft. That is correct: the
title is a claim about what an institution appointed the student as, and this platform
verifies claims rather than improving them. If a title is genuinely opaque to a foreign
reader, the sanctioned routes already exist — a gap question, or the counsellor's own edit —
never a silent rewrite at generation.

### Guides read but not mined

**Cambridge's *CVs and Cover Letters for PhDs and Postdocs*** (43pp) was downloaded and
opened, then set aside on its own instruction: "Undergraduates and Masters students should
ask for the edition of CVs and Cover Letters written especially for them" — which is the
booklet already read. S-039's audience rule applied to a source rather than to a section.

**Lancaster's academic CV guide** (13pp) is for academic *jobs* and says so; its one
transferable line is the Education section — "ensure to include the name of your supervisor,
dates and title of thesis" — which is S-040, now with a third source. Its "Do not include
any reference to hobbies/interests" is the academic-job reading and sits directly opposite
Harvard GSD and HKS asking for them at master's admission: S-039's split, seen from a third
direction.
