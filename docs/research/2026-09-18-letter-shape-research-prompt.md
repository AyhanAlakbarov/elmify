# Parallel research prompt — the shape of a master's motivation letter, by system and by field

Status: **approved by the owner** (2026-09-18), with one correction folded in below: **no human
reviews the finished letter.** Per-letter counsellor review was struck as friction the product cannot
carry at volume, so the letter has to leave the engine right the first time — which is why this pass
asks for rules precise enough to draft against unaided, not guidance a reviewer would apply by eye.
Scope settled the same day: worldwide; four discipline families; official pages + university writing
centres + letters a university itself publishes as successful; two engines (GPT Researcher on
Tavily+Exa, plus one independent deep-research run), reconciled by hand. The owner also intends a
later pass re-examining `L-001`–`L-073` themselves; this brief does not do that.

Paste the block below into GPT Researcher, Gemini Deep Research, Claude, or any research agent. It
is self-contained: it assumes no access to this repository. For GPT Researcher, run it **one system
at a time** (six runs, each with the whole prompt and the line "Report only system N in this run")
— two broad multi-destination runs in the 2026-09-14 pass hung and were killed at the idle limit.
The second engine gets the whole prompt in one go. Diff the outputs; disagreement is the signal.

Output merges into a new `docs/research/letter-shape-rules.csv` (IDs `M-0NN`, columns below) plus a
system map and a merge note. Nothing here changes code; the engine follow-ups that read this
catalog are planned after it exists.

## Why this pass exists

Three passes have already been run on motivation letters and their findings are not to be
re-derived: `letter-rules.csv` (73 `L-` rules: limits, prompts, document kinds, AI policy),
`2026-08-22-letter-ruleset.md` (what each of ~25 funders requires), and
`2026-09-14-letter-storytelling-evidence.md` (19 `N-` findings on story, voice and what each
reader rewards). Together they settled **what** goes in a letter. What none of them asked is **how
the letter sits on the page**: which part comes first and how much of the letter each part takes,
what a strong opening and closing do, whether the document looks like a letter (date, addressee,
salutation, sign-off) or an essay, how naming a professor or a group is received, and how any of
this shifts by field. The only full skeleton found so far is Cambridge's (L-072, one source), and the
paragraph orders the engine uses today were written to make the code work, not sourced.

---

## THE PROMPT

You are doing source-grounded research for a product that drafts **master's-degree motivation
letters and statements of purpose** for international applicants worldwide. **No human reviews the
finished letter before the student uses it**, so every rule you report must be precise enough for
software to draft against and check — "keep it professional" is useless; "the letter is addressed
to the programme coordinator by name where the programme page names one, otherwise to the selection
committee" is usable. The product already knows each funder's word limits, question sets, AI-use
policies and what readers reward; **do not research those**. This pass is about the **shape** of the
document: the order and weight of its parts, its formalities, its register, and how personalisation
(naming people, groups, papers, modules) is received — by application system and by field of study.

### Ground rules (apply to everything below)

- **Cite a primary source for every claim.** A university's, department's or funder's own page,
  official guidance, or an official template or form. University writing-centre pages (MIT
  Communication Lab, Purdue OWL, Berkeley Graduate Division, DAAD's advice sheet and the like) are
  admitted as **guidance**, labelled T2, never as requirement.
- **Example letters are read for shape only.** A letter a university or funder itself publishes as
  a successful or model example (an admissions page, an open textbook, a faculty page) may be used
  to report *order, proportion, opening and closing moves, formalities* — never wording, and never
  as evidence of a rule. Coaching sites, essay-mill samples, forum posts and "sample motivation
  letter" blogs are **excluded** entirely; they are where the clichés this product must avoid come
  from.
- **Separate binding from advisory.** Binding = the funder or department states it in writing and
  breaking it risks rejection (a prescribed form, a required header, a required language or
  salutation). Advisory = convention or guidance with no published rule behind it. Almost
  everything about shape will be advisory; say so rather than upgrading it.
- **Master's level only.** US undergraduate essay advice and UCAS undergraduate statements do not
  transfer; when a source is undergraduate, say so and drop it. PhD statements of purpose may be
  used **only** where a department publishes one guide for all graduate applicants and says so.
- **Report gaps honestly.** "No published shape convention found for X" is a finding. Do not fill a
  gap with general advice. Where a country publishes nothing, do the mapping exercise in §3
  instead.
- Note the date and application cycle of every source.

### 1. The six application systems

Letters cluster by system, not by border. Organise every finding under exactly one of these:

| System | What it is | Known members (extend, confirm or move them) |
|---|---|---|
| **A. CONTINENTAL_LETTER** | A letter of motivation to a programme: *Motivationsschreiben*, *lettre de motivation*, *motivatiebrief*, *lettera motivazionale*, *carta de motivación*, *мотивационное письмо*. Often literally a letter. | Germany, Austria, Switzerland, France, Belgium, Netherlands, Italy, Spain, Portugal, Sweden, Denmark, Norway, Finland, Poland, Czechia, Hungary, the Baltics, Türkiye (university admissions), Russia (university admissions) |
| **B. UK_STATEMENT** | A personal statement / statement of academic purpose in essay form, no letter formalities, to a taught or research master's. | United Kingdom, Ireland; **to confirm:** Australia and New Zealand universities, Singapore (NUS, NTU, SMU), Hong Kong, Malaysia, South Africa |
| **C. NORTH_AMERICAN_SOP** | A statement of purpose, department-read, often paired with a separate personal history / diversity statement. | United States, Canada; **to confirm:** KAUST (Saudi Arabia), MBZUAI and Khalifa (UAE), HBKU and the Education City branch campuses (Qatar), other US-modelled institutions in the Gulf |
| **D. SCHOLARSHIP_NARRATIVE** | A funder's own essay or answer set, read by a selection committee against published criteria, distinct from the university's document. | DAAD, Chevening, Fulbright, Commonwealth, Erasmus Mundus, Eiffel, Swedish Institute, Stipendium Hungaricum, Türkiye Bursları, Australia Awards, New Zealand Manaaki, Gates Cambridge, Rhodes; **to establish:** Brunei Darussalam Government Scholarship, Bahrain, Saudi (KAUST Fellowship, Saudi government grants for foreign students), UAE and Qatar national scholarships, Chinese university-level scholarships distinct from CSC, Brazil PEC-PG, Mexico AMEXCID, Chile ANID, Argentina, Colombia ICETEX, South Africa NRF, Mastercard Foundation Scholars, Egypt, Morocco AMCI, Rwanda, Kenya, Nigeria, Ghana, Ethiopia |
| **E. RESEARCH_PLAN_FORM** | A prescribed form with fixed headings: past study → research theme → plan. | MEXT (Japan), China Scholarship Council study plan, GKS study plan (Korea), Swiss ESKAS proposal; **to confirm:** Taiwan MOE, Japanese and Korean university-level admissions outside the scholarships, Chinese universities admitting self-funded international master's students |
| **F. IMMIGRATION_STATEMENT** | A statement to a visa authority, not a university; false statements carry legal consequences. | Australia Genuine Student, Canada study-permit letter of explanation; **to confirm:** New Zealand student visa, any Gulf student-visa statement, US (oral interview only — confirm there is no written statement) |

Systems E and F are already well documented in the earlier passes. For them, answer only §2
questions 2, 3 and 4 and the §3 confirmations; do not re-derive the forms.

### 2. Six questions, asked of every system × field cell

Answer each for the system as a whole, then for each of the four **discipline families** in §4
where the answer differs. Where it does not differ, say "no field-specific guidance found" — that
too is a finding.

**Q1. Order and weight.** Which parts does the document contain and in what order? Roughly what
share of the length does each take? Is any order prescribed (a form, a template, a stated
"structure your letter as…"), or is it convention? Where a department publishes a checklist rather
than an order (UCL's seven areas, KTH's four, DAAD's a–d), report the checklist and say explicitly
that no order is published.

**Q2. Opening and closing.** What does a strong opening *do* in this system — name the programme,
state the goal, pose the research question, begin with the applicant's present position? What does
the closing do — restate the fit, state availability, thank, sign? The product already holds the
negative rules (no "I have always wanted…", no restating the paragraph, no repeating the CV); it
needs the **positive** ones, sourced.

**Q3. Formalities.** Is it a letter or an essay? Date, sender address, addressee (a named person, a
committee, a department), salutation form and level of formality (*Sehr geehrte Damen und Herren*,
*Madame, Monsieur*, *Dear Admissions Committee*, none), sign-off, handwritten or typed signature,
name and programme in a header, page layout (one page, letterhead-style, headings allowed). Where a
system's members differ (French vs German salutation conventions inside system A), report both.

**Q4. Personalisation.** How is naming a specific professor, research group, lab, paper, module or
facility received — expected, tolerated, penalised? Where does it sit in the document and how much of
it? Distinguish research-track fit (a named group whose work matches the applicant's) from taught
fit (a named module or specialisation). Report explicit warnings (Göttingen: "do not retell the
information about the programme from our web page"; Chevening on cut-and-paste) and explicit
invitations (US departments asking for faculty of interest; the Cambridge booklet's "who or what
your main academic influences have been"). Note whether any system says contacting a professor
before applying is expected, optional or discouraged.

**Q5. Register.** Formal-letter register, academic-essay register or first-person narrative?
Sentence length and jargon guidance where published (Cambridge: 25–30 words; Berkeley: "write in the
style of your discipline"). Whether headings or bullet points are acceptable. Person and tense
conventions.

**Q6. Scoring.** Where a system or department publishes how the document is scored — weights,
rubric criteria, band descriptors — report it. The product already has DAAD, Chevening, Commonwealth,
KTH, Leiden, LMU and Groningen; report those only if you find a newer cycle, and add anything new.

### 3. The country map — worldwide by assignment, not by omission

Every country an applicant might name must map to a system. For each country below, report:
**(a)** whether any national body, major university or scholarship publishes a **template, form or
structural rule** for the master's motivation document; **(b)** if yes, which system it belongs to
and the evidence; **(c)** if no, which system its major institutions' published requirements most
resemble, with the specific page that shows the resemblance, and a confidence grade. "Assigned to A
because the University of X's page asks for a *letter* addressed to the faculty with a stated
salutation" is the standard; "probably continental" is not.

Cover at minimum, by name: **China** (CSC and non-CSC university admissions, Hong Kong, Macau),
**Japan** (MEXT and university direct admissions), **South Korea** (GKS and university admissions),
**Singapore**, **Brunei**, **New Zealand**, **Bahrain**, **United Arab Emirates**, **Qatar**,
**Saudi Arabia**, **Russia** (Open Doors and university admissions), **South America** (Brazil,
Argentina, Chile, Colombia, Mexico, Peru), **Africa** (South Africa, Egypt, Morocco, Kenya, Nigeria,
Ghana, Rwanda, Ethiopia), **South Caucasus** (Georgia, Armenia, Azerbaijan), **Central Asia**
(Kazakhstan, Uzbekistan, Kyrgyzstan, Tajikistan, Turkmenistan). Add any other country where you find
a distinctive published shape.

Flag every country whose universities follow one system while its national scholarship follows
another (Türkiye and Hungary already look like this); the product must not apply a funder's shape to
a university letter.

### 4. Discipline families

Map each finding to the family it applies to; use `all` when the source does not distinguish.

- **research** — STEM, natural and life sciences, engineering, computing, mathematics: a research
  problem, methods, technical preparation.
- **humanities-social** — humanities and social sciences: an intellectual question, a literature, a
  method of enquiry; departments in this family often say explicitly that they do not want a
  STEM-style problem statement.
- **professional** — business (including MBA), law, public policy, public health, education,
  social work, clinical fields: career outcome, practice, impact.
- **arts-design** — fine arts, design, architecture, music, film: a portfolio-led statement whose
  shape is set by the portfolio.

Report where a department in one family publishes guidance that **contradicts** another family's
(e.g. a humanities department discouraging the "faculty of interest" paragraph a STEM department
requires). Those contradictions are the reason the families exist.

### 5. What NOT to research

Already settled and cited by ID in the product; do not spend sources on them:

- word, character and page limits; question sets and prompt archetypes; which document kinds exist
  (short-answer set, continuous letter, two statements, prescribed research form, consortium form,
  video) — `L-001`–`L-073`;
- storytelling, unifying theme, "authentic voice", AI-detection and humaniser tools, evidence-then-
  interpretation, STAR for short answers, the swap-the-university-name fit test — `N-01`–`N-19`;
- AI-use and third-party-authorship policy — `L-` ai-policy rows;
- reuse of a core letter across programmes — `L-061`.

### OUTPUT FORMAT

**Rules** as CSV rows with exactly these columns:

```
"ID","Rule","Applies to","System","Discipline family","Scope","Binding or advisory","Source (tier)","Source URL [provenance]","Verified for cycle","Confidence"
```

- `ID` — sequential, prefixed `M-` (M-001, M-002, …)
- `Rule` — one sentence, specific enough to implement or check against
- `Applies to` — one of `order`, `proportion`, `opening`, `closing`, `formalities`,
  `personalisation`, `register`, `scoring`, `exception`
- `System` — `A`–`F` as named in §1
- `Discipline family` — `research`, `humanities-social`, `professional`, `arts-design`, or `all`
- `Scope` — `system`, a country, or a named institution or funder
- `Binding or advisory` — as defined in the ground rules
- `Source (tier)` — T1 official funder/university/department page, form or template; T2 university
  writing centre or named admissions professional; T3 secondary or press (use sparingly, and only for
  quoted T1 wording you could not reach directly)
- `Verified for cycle` — the cycle the source refers to, or `evergreen`
- `Confidence` — high / medium / low

**The country map** as a second table:

```
"Country","System","Has published template or rule (yes/no)","Evidence URL","Assignment reasoning","Confidence"
```

**Finally**, list the questions you could not answer from primary sources and say what kind of
source would settle each — a live application portal, an authenticated form, a department's PDF
that has moved. This list matters as much as the findings.
