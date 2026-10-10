# Parallel research prompt — motivation letters + open-source landscape

Paste the block below into Gemini Deep Research, Claude, or any research agent. It is
self-contained: it assumes no access to this repository. Run it in as many tools as you like and
diff the outputs — disagreement between them is itself a signal about which claims are solid.

Output merges into `docs/research/letter-rules.csv` (same column layout as `cv-rules.csv`) and a
companion landscape note.

---

## THE PROMPT

You are doing source-grounded research for a product that generates **master's-degree application
documents** — CVs and motivation letters / statements of purpose — for international applicants
worldwide, then has a human counselor review them. Accuracy of sourcing matters more than
completeness. Two tracks; report both.

### Ground rules (apply to everything below)

- **Cite a primary source for every claim.** A university's or funder's own page, official
  application guidance, or an official template file. University writing-centre pages are
  acceptable but must be labelled as guidance, not requirement.
- **Never infer a requirement from an example.** If a page shows a sample letter but states no
  rule, that is not a rule.
- **Separate binding from advisory.** Binding = the funder or university states it in writing and
  breaking it risks ineligibility or rejection. Advisory = convention, coaching advice, or
  widely-repeated practice with no published rule behind it. When in doubt, mark advisory.
- **Distinguish master's-level from undergraduate.** Most published advice online is US
  undergraduate admissions essay advice and does **not** transfer. Say so explicitly when a source
  is undergraduate-level, and do not include it as a master's rule.
- **Report gaps honestly.** "No published policy found for X" is a valuable finding. Do not fill a
  gap with plausible-sounding general advice.
- Note the date and application cycle each source refers to.

### TRACK A — How master's motivation letters actually work

**A1. Are these one document or several?** Cover the whole world, not only the Anglosphere and
western Europe. For each named document below report: what it is called (including the local-language
name), what it must contain, required or typical length, and whether content that works in one
would actively hurt in another. Cite official admissions/funder pages, not blog comparisons.

- **United States** — statement of purpose; personal statement / personal history statement, where
  some universities require *both* as separate documents with different briefs.
- **United Kingdom** — personal statement (note: the master's-level one is not the UCAS
  undergraduate statement; do not conflate them).
- **Continental Europe** — motivation letter / *Motivationsschreiben* (DE/AT/CH), *lettre de
  motivation* (FR), *brief motivatie* (NL), and the Nordic systems.
- **Erasmus Mundus / EU funders** — letter of motivation, plus any consortium-specific form.
- **China** — China Scholarship Council (CSC) and Chinese universities: the **study plan /
  research proposal** (学习计划), which is typically a *separate mandatory document* rather than a
  motivation letter. Report its brief and length.
- **Japan** — MEXT scholarship: the **field of study and research programme plan**. Again a
  distinct document with its own official form.
- **South Korea** — Global Korea Scholarship (GKS): **personal statement AND study plan**, both
  required, with different briefs. Report both.
- **Türkiye** — Türkiye Bursları (Türkiye Scholarships): letter of intent / motivation
  requirements, and anything the online application prescribes.
- **Australia** — university statements of purpose, **and separately** the **Genuine Student (GS)
  requirement** for the student visa, which replaced Genuine Temporary Entrant. Establish clearly
  whether GS is an admissions document or an immigration one, what it asks, and what the
  consequences of a false or third-party-written statement are. Treat this as high priority.
- **Canada** — letter of intent, and any equivalent statement required for the study permit.
- Also check, more briefly: Singapore, Hong Kong, Russia (Open Doors), Italy (MAECI / Invest Your
  Talent), Switzerland (ESKAS), and any other major destination you find with a distinctive brief.

**A1b. Which of these are genuinely different document KINDS?** Conclude explicitly: is a study
plan a motivation letter with different section headings, or a different document requiring
different source material (e.g. a proposed research topic, a supervisor, a timeline, a budget)?
And flag any document that is submitted to an **immigration authority rather than a university**,
since a false statement there carries legal consequences beyond rejection.

**A2. Structure.** What sections or beats do these documents actually contain? Is there a
published expected structure anywhere, or is structure purely convention? Report what is
prescribed versus what is merely common.

**A3. Narrative weight — the key question.** How much does *storytelling* matter versus a
factual statement of academic fit, and **does this differ by country or system**? A widely-held
belief is that US applications reward personal narrative while German and Nordic ones reward
factual fit. Find evidence for or against this. Admissions-office statements, published selection
criteria, and admissions-officer interviews are the sources that count; coaching-industry blogs
are not evidence.

**A4. Length and format limits.** Word counts, character counts, page limits, font and file-format
requirements. Distinguish published hard limits from convention. Cover at minimum: DAAD, Erasmus
Mundus joint masters, Chevening, Fulbright, Swedish Institute (SISGP), Stipendium Hungaricum,
Australia Awards, Gates Cambridge, Rhodes, Eiffel, Holland Scholarship, Commonwealth Scholarships,
China Scholarship Council, MEXT, Global Korea Scholarship, Türkiye Bursları, Swiss ESKAS, plus the
application systems used by major destination universities.

**A5. Prompt archetypes.** What questions do these applications actually ask? Collect the real
wording of prompts where published. Group them into recurring archetypes (e.g. "why this
programme", "why this country", "career plans", "leadership example", "how will you contribute on
return"). Note which funders ask several short answers instead of one continuous letter.

**A6. Reuse across applications.** Is adapting one core letter across multiple programmes normal
practice, or is it detected and penalised? Look for admissions statements about generic or
recycled letters, similarity checking, and whether any system runs plagiarism detection across
applicants or against an applicant's own prior submissions.

**A7. Failure modes.** What do admissions offices say gets a letter rejected or discounted?
Specifically: wrong institution named, unsupported claims, generic content, over-long, missing a
required question, wrong language. Cite where stated.

**A8. Language requirements.** When must the letter be in a language other than English, and who
states it (e.g. French for certain Eiffel programmes, the programme's teaching language elsewhere)?

**A9. AI-use and third-party-authorship policy.** What do universities and funders publish about
AI assistance *specifically for personal statements and motivation letters* at master's level, and
about third-party or agency-written applications? Note that Cambridge, Oxford and Chevening are
known to publish positions; check whether DAAD, Erasmus Mundus/EACEA, Fulbright, SISGP, Rhodes,
Australia Awards and the Commonwealth Scholarship Commission publish anything at all. "Nothing
found" is a real answer here and should be reported as such rather than assumed permissive.

**A10. Craft.** From writing instruction rather than admissions policy: how do skilled writers
build a through-line connecting a person's history to a stated goal? What distinguishes a letter
that reads as authored from one that reads as an assembled list of achievements? Prefer university
writing centres, published books on graduate admissions writing, and named admissions
professionals. Label all of this as craft guidance, never as requirement.

### TRACK B — Existing open-source solutions worth adopting

We would rather adopt and improve something that exists than build from scratch. Survey what is
actually out there, for **both** CVs and motivation letters.

For each project report: name, URL, licence, whether it is actively maintained (last release and
commit activity), what it does, and — the important part — **what specifically could be reused**
versus what would have to be rewritten.

Cover these categories:

- **CV/résumé data schemas.** Is there a credible standard for representing a CV as structured
  data? Examine JSON Resume, the EU's Europass / European Learning Model (ELM) schema and its
  JSON/XML formats, HR-Open, and anything else in use. Which of these are real standards with
  adoption versus one person's repository?
- **CV renderers.** Projects that turn structured CV data into PDF or DOCX — e.g. RenderCV,
  Reactive Resume, OpenResume, resume-cli. Assess font embedding, text-layer quality, template
  range, and whether output can meet a funder's fixed template.
- **Europass tooling.** Any open-source library that produces a valid Europass CV, and whether the
  EU publishes an official schema or API for it.
- **Document extraction / OCR pipelines.** Projects that turn a scanned transcript or CV into
  structured data — e.g. Docling, Unstructured, MinerU, and dedicated résumé parsers. Note
  licences carefully; several are open-core with restricted commercial terms.
- **Motivation letter / SOP generators.** Be sceptical here — expect the field to be mostly thin
  prompt collections and paid SaaS. Report honestly if little of substance exists, and say what
  the best of it actually is.
- **Agent skills and prompt libraries** for résumé and admissions-essay writing, including
  published Claude/Cursor/Codex skills and curated prompt repositories. Assess whether any encodes
  real domain rules or is merely generic advice.
- **Taxonomies we would consume rather than invent.** UNESCO **ISCED-F** fields of education
  (for classifying a programme's discipline), and **ESCO** for skills — availability, licence,
  machine-readable form, and granularity.

For each, end with a one-line verdict: **adopt / adapt / reference only / ignore**, and why.

### OUTPUT FORMAT

**Track A** as CSV rows with exactly these columns, so they merge into an existing ruleset:

```
"ID","Rule","Applies to","Scope","Binding or advisory","Source (tier)","Source URL [provenance]","Verified for cycle","Confidence"
```

- `ID` — sequential, prefixed `L-` (L-001, L-002, …)
- `Rule` — one imperative sentence, specific enough to implement or check against
- `Applies to` — e.g. `structure`, `length`, `language`, `prompt`, `ai-policy`, `validation-flag`
- `Scope` — `universal`, a country, a system, or a named funder
- `Binding or advisory` — as defined in the ground rules
- `Source (tier)` — T1 official funder/university page or template; T2 university writing centre or
  named admissions professional; T3 secondary or press
- `Verified for cycle` — the cycle the source refers to, or `evergreen`
- `Confidence` — high / medium / low

**Track B** as a table, plus a short prose verdict on the two or three projects genuinely worth
adopting.

**Finally**, list the questions you could not answer from primary sources, and say what kind of
source would settle each. This list matters as much as the findings.
