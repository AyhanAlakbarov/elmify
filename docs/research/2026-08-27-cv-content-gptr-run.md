# CV content + tailoring research — run 1 of 3 (GPT Researcher / Tavily)

Prompt: `docs/research/2026-08-27-cv-content-research-prompt.md`, Track B only.
Run 2026-08-27. Cost $0.037. 20 source slots, ~14 distinct domains.
Runs 2 and 3 (Gemini Deep Research, Claude Deep Research) are being done separately;
diff all three before drawing conclusions, as with `cv-style-rules.csv`.

## Headline

**No empirical evidence was found that tailoring a CV to a specific master's programme
changes admissions outcomes.** No study, no audit experiment, no published outcome data,
no admissions-office policy stating it. The question appears unstudied rather than
studied-and-refuted -- which is a different thing and matters for what we build.

Source classification returned by the run: **0 published policy, 0 empirical studies,
1 admissions professional on record, 49 coaching/marketing.**

## Source-quality audit (corrected)

The generated report claimed none of its sources were portals, agencies or job boards.
That is contradicted by its own source list, so here is the honest breakdown from the URLs:

| Category | Domains |
| --- | --- |
| Degree portals / lead-gen | educations.com (x3), mastersportal.com, mastergradschools.com, accessmasterstour.com |
| Commercial editing services | wordvice.com (x2) |
| Study-abroad agencies | ukstudyonline.com (x2), masters.goalisb.com |
| Job boards | uk.indeed.com (x2) |
| Social media | facebook.com/groups/... |
| University *marketing* blogs | graduate.northeastern.edu/knowledge-hub, online.kcl.ac.uk/blog |
| University careers services (guidance, not admissions policy) | careers.ox.ac.uk (x2), careercenter.fresnostate.edu |
| Academic domain | pmc.ncbi.nlm.nih.gov/articles/PMC10860585 |

**Zero admissions-office policy pages. Zero European admissions offices.** Not one
uni-assist page, not one German/Dutch/Nordic university admissions rubric.

Two sources need a caveat rather than a dismissal:
- **careers.ox.ac.uk** is a real careers service, but the retrieved passage is about
  *academic job* applications, not master's admissions -- one of the three
  non-transferable domains the prompt names.
- **PMC10860585** is the only academic-domain source. Its retrieved passage is about the
  structural difference between US and European graduate admissions (direct-to-advisor
  contact, interview norms), not about CVs. It is not a CV study.

## B1 -- empirical evidence

None found.

Every source asserting that tailoring matters is category (d). They are unanimous, and
unanimity here is worthless: ~14 sources repeating one unevidenced claim is one
unevidenced claim, not fourteen corroborations. Several are commercially interested in
the applicant believing their CV needs professional work.

## B2 -- admissions offices on the record

One statement only, and it is weaker than it first looks. Mark I Khan, **Director of
Marketing and Enrolment** at Boston University, on committees looking for "cultural fit"
-- a claim about the whole application, not about CV tailoring, from a marketing-side
role, at a US institution. Not a European master's admissions office, and not a policy.

No admissions office was found stating either that it wants a tailored CV or that
tailoring makes no difference.

## B3 -- which tailoring behaviour has support

| Behaviour | Support found |
| --- | --- |
| Reorder existing material so relevant items lead | none beyond coaching |
| Select what appears under a page constraint | none beyond coaching |
| Rewrite descriptions in the programme's vocabulary | none beyond coaching |
| **Add competencies not evidenced elsewhere** | **no published guidance either FOR or AGAINST** |

The fourth row is the important one, and it resolves an open argument in our own design
discussion: neither position had evidence. The claim that unevidenced soft skills are
fraud-adjacent is unsupported; so is the claim that they are fine because everyone adds
them. Nobody has published on it. That should be recorded as an open question, not
settled by either prior.

## B4 -- misrepresentation

No published policy or case found on CVs tailored to the point of misrepresentation, and
no institution found that distinguishes "emphasis" from "fabrication" in writing.

Note this does not contradict `cv-rules.csv` R-050/R-091/R-092, which are about
AI-generated content and negative attestations on application forms -- a different
question from tailoring, and already carrying their own undergraduate-essay caveat.

## Supporting context

Nothing usable. No published data on review time in European master's admissions was
found. The 4-12 minute figures circulating are US undergraduate.

## What this changes

1. **Do not build the tailoring subsystem on a claimed evidence base.** There isn't one.
   Build it, if at all, as an explicit product bet.
2. **Absence of evidence is not evidence of absence here.** The question is unstudied.
   Tailoring may well work; nobody has checked.
3. **Evidence intake (subsystem 1) is unaffected.** Extracting real facts from a repo or a
   publication improves accuracy and completeness regardless of whether tailoring matters.
   It rests on nothing this null result undermines.
4. **Reordering and selection are low-risk whatever the answer**, because they assert
   nothing new. If we build one part of tailoring first, build those.

## What a real study would need to measure

Correlation between tailoring and admit rates across programmes; which CV elements
committees actually weigh; the review process and criteria at master's level; and
longitudinal outcomes. None of this exists publicly. Treat any vendor claiming otherwise
as selling something.
