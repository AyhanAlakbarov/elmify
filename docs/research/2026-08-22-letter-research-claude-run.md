# Letter + tooling research — raw output (Claude web deep research)

Authoritative file supplied by the user (compass_artifact_wf-255b094c...). One of the
runs of docs/research/2026-08-22-letter-research-prompt.md; its findings were merged
into letter-rules.csv and 2026-08-22-letter-ruleset.md on 2026-08-22. Archival source.

---

# Source-Grounded Research: Master's Application Documents (Motivation Letters & CVs) + Open-Source Tooling

## TL;DR
- **Master's "motivation letters" are not one document but a family of distinct KINDS**: narrative motivation letters/SOPs (university admissions), structured multi-question funder forms (Chevening, SISGP, Australia GS), and research-source documents (China CSC study plan, Japan MEXT Field of Study plan, Korea GKS study plan) that require a proposed topic, sometimes a named supervisor, and a timeline. Critically, **Australia's Genuine Student statement and Canada's letter of explanation go to an IMMIGRATION authority**, so a false or third-party-fabricated statement carries legal (misrepresentation) consequences beyond mere rejection.
- **The "US = personal narrative, Germany/Nordic = factual fit" belief is only partly true.** At the graduate (not undergraduate) level, US official guidance itself stresses academic fit and explicitly calls the SOP "not a personal essay"; the clearest "reflective and factual" instruction is German (Göttingen/DAAD). The "US grad = storytelling" reputation is largely imported from US *undergraduate* essay advice that does not transfer.
- **For Track B, three things are genuinely worth adopting**: JSON Resume (CV schema, MIT), RenderCV (renderer, MIT), and the ISCED-F/ESCO taxonomies (free, machine-readable). Europass ELM is the authoritative EU schema but heavy; document-extraction tools require careful license triage (Docling Apache-2.0 vs MinerU's custom license vs Marker's OpenRAIL-M revenue thresholds).

## Key Findings
1. **Document kinds differ fundamentally.** A study plan is not a motivation letter with new headings — the CSC, MEXT and GKS study plans require *different source material*: a proposed research topic, sometimes a named supervisor, a year-by-year timeline. A generator must gather that data, not re-run a motivation-letter template.
2. **Immigration vs admissions is the highest-stakes distinction.** Australia GS (Home Affairs) and Canada LOE (IRCC) are immigration documents about genuine intent, ties and funding. A false statement can trigger visa refusal and a formal misrepresentation finding.
3. **Funder length/format limits are frequently hard and sometimes disqualifying.** Australia GS is capped at 150 words per answer; SISGP mandates its own template (CV max 3 pages) or applications are disqualified; Fulbright caps each essay at 600 words / 1–1.5 pages, "under no circumstances" exceeding two pages.
4. **AI and third-party-authorship policies are published by some funders and silent for others.** Chevening explicitly prohibits AI-generated answers and runs detection; Oxford and Cambridge require own-work at graduate level. DAAD, Erasmus Mundus/EACEA, Fulbright, SISGP, Rhodes, Australia Awards and the Commonwealth Scholarship Commission publish little or nothing specific to the motivation letter — reported here as gaps, not permission.
5. **A credible open CV data standard exists** (JSON Resume, MIT) alongside the authoritative-but-heavy EU Europass ELM. For rendering, RenderCV (MIT) is the strongest reusable engine.

## Details

### Track A — how these documents actually work

**A1 / A1b — one document or several; which are genuinely different kinds.**

- **United States.** Two distinct documents at many universities. The UC Berkeley Graduate Division requires BOTH a Statement of Purpose ("describe your aptitude and motivation for graduate study… preparation for this field of study, your academic plans or research interests, and your future career goals. Please be specific about why UC Berkeley would be a good intellectual fit") AND a Personal History Statement ("describe how your background and life experiences have influenced your decision to pursue a graduate degree… formative experiences, values, or motivations"), with the explicit rule that "The Personal History Statement should not duplicate the Statement of Purpose." Content that belongs in the PHS (adversity, identity, personal formation) can actively hurt in the SOP, which US guidance frames as academically focused.
- **United Kingdom.** The master's-level personal statement is a taught-postgraduate admissions document written directly to the university/department — NOT the UCAS undergraduate statement. Do not conflate. Length is set per-university; there is no central UK master's word count.
- **Continental Europe.** Motivation letter / *Motivationsschreiben* (DE/AT/CH), *lettre de motivation* (FR), *motivatiebrief* (NL), and Nordic motivation letters. German university/DAAD guidance emphasizes analytical/academic writing and a factual tone; typical length 1–2 pages.
- **Erasmus Mundus.** Each consortium sets its own brief; a motivation letter or SOP tailored to the specific multi-country joint programme is standard, and some consortia require a Europass-format CV. Official EACEA/EMJM webinar material advises aligning with EMJM objectives (mobility, cooperation, diversity) and focusing on impact.
- **China (CSC).** The study plan / research proposal (学习计划 / 研究计划) is a separate mandatory document. The official "Regulations on the Management of Chinese Government Scholarship" require "Research or study plans (no less than 200 words)"; many universities require substantially more (commonly no less than 800 words for postgraduate applicants, per university guidance). It requires a research topic and often supervisor contact — a different KIND of document.
- **Japan (MEXT).** The Field of Study and Research Program Plan (研究計画書) is a distinct official form. The embassy-recommended format is limited to 2 pages including instructions, and asks for research background, proposed topic/theme, goals and a timeline.
- **South Korea (GKS).** TWO required documents with different briefs, administered by NIIED: a Personal Statement (Form 2 — backward-looking: who you are, what shaped you) and a Study Plan (Form 3 — forward-looking: Korean-language plan, study plan, career). The graduate track adds a Research Proposal.
- **Türkiye (Türkiye Bursları / YTB).** A letter of intent written directly into the online portal within a character limit, evaluated on academic status, career goals, consistency of preferences, and the content of the letter of intent.
- **Australia.** University SOPs are admissions documents. Separately, the **Genuine Student (GS) requirement is an IMMIGRATION requirement** for the Subclass 500 visa (Department of Home Affairs), applying to applications lodged on or after 23 March 2024 (it replaced the Genuine Temporary Entrant requirement). It is answered as questions directly in the online visa form, not a separate essay; Home Affairs "prefer applicants to respond to the above questions in the application form rather than attaching a separate GS statement." It is assessed under Ministerial Direction No. 106 (signed by then-Minister for Home Affairs Clare O'Neil), which commences 23 March 2024.
- **Canada.** A letter of explanation (a.k.a. study plan / SOP) attached to the study permit application to IRCC. IRCC lists it as recommended, not always required. It is an immigration document about intent, ties and funding — distinct from a university SOP.
- **Others (briefly):** Singapore/Hong Kong universities use conventional SOPs; Russia (Open Doors), Italy (MAECI / Invest Your Talent), and Switzerland (ESKAS) each have their own funder forms — ESKAS uses a prescribed research-proposal form.

**A2 — Structure.** Prescribed structure is the exception. Where funders use forms (SISGP, GKS, Chevening, Australia GS), structure is imposed by the form's questions. For free-form university motivation letters/SOPs, the common structure (intro → academic background → fit with programme → career goals → conclusion) is convention, not a published requirement.

**A3 — Narrative weight (the key question).** The "US = story, Germany/Nordic = fit" belief is only partly supported by primary sources.
- At the GRADUATE level, US official guidance itself stresses academic fit: **Cornell Graduate School** says the SOP is "an academically focused essay, not necessarily a personal essay"; **UPenn Career Services** says the tone "will resemble a cover letter more than a narrative essay for undergraduate admissions."
- Germany is the clearest "factual" case: the **University of Göttingen** page (built on the DAAD manual) instructs applicants to "Deal with your topics in a reflective and factual way" and to "Avoid all kinds of platitudes, flowery phrases and flattery."
- Nordic universities (Lund, Copenhagen, Oslo) emphasize programme fit, competence and career goals, often via structured templates; Copenhagen's lead instruction is "Focus on the study programme and its content."
- **Nuance:** DAAD's own scholarship page invites describing "your personality" and "personal reasons," so the contrast is one of emphasis and tone, not a hard binary. The strong "US grad = personal narrative" belief is largely an artifact of US UNDERGRADUATE essay advice that does not transfer to master's applications.
- **Bottom line for the product:** treat storytelling as *subordinate to* a stated academic/career purpose everywhere; dial personal narrative slightly up for US personal-history statements and slightly down for German/Nordic letters — but never toward "life story."

**A4 — Length/format limits (published hard limits vs convention).**
- **Chevening:** four essays. *The specific per-essay word limit could not be confirmed on Chevening's own current public guidance*; widely reported as 500 words (some cycles report 300). Flag for cycle verification (see gaps).
- **DAAD:** motivation letter on no fewer than one and no more than three pages (per DAAD scholarship-applicant guidance); DAAD provides no sample.
- **Erasmus Mundus:** per-consortium; no single limit.
- **SISGP (Swedish Institute):** mandatory SI motivation-letter form (PDF) and mandatory SI CV template (max 3 pages); using the wrong format or exceeding length "will disqualify" the application.
- **Australia GS:** "There is a text limit of 150 words per response. All responses must be in English." (Home Affairs, official GS page.)
- **CSC:** study plan no less than 200 words (official regulation); universities often require ≥800.
- **MEXT:** Field of Study plan max 2 pages (embassy format).
- **Fulbright Foreign Student:** per the official 2026–27 Slate Instructions, "each essay must be limited to 600 words or 1 to 1.5 pages. Under no circumstances should the essay exceed two pages."
- **Gates Cambridge, Rhodes, Eiffel, Holland Scholarship, Stipendium Hungaricum, Commonwealth, Swiss ESKAS, GKS graduate Study Plan:** length is set per-scheme and was not confirmed from a primary current-cycle source in this research (see gaps).

**A5 — Prompt archetypes (with real wording where published).** "Why this programme / fit" (Berkeley SOP; Chevening study essay), "leadership example" (Chevening, STAR method), "networking / relationship-building" (Chevening), "career plan / contribution on return" (Chevening, SISGP, Fulbright), "who you are / personal history" (Berkeley PHS; GKS Form 2), "why this country" (Australia GS: "Explain why the applicant wishes to study this course in Australia with this particular education provider"; Canada LOE; CSC study plan). Several funders ask multiple short answers rather than one continuous letter: Chevening (four essays), Australia GS (four questions, plus a fifth for onshore/prior-student-visa applicants), and SISGP (form questions).

**A6 — Reuse across applications.** Adapting a core letter across university applications is normal, but recycled/generic content is a named failure mode: Erasmus Mundus reviewers flag statements that do not engage the specific multi-country structure, and CSC guidance warns against a "generic study plan that could apply to any country or university." Chevening runs plagiarism and AI-detection tooling. No primary evidence was found that any system checks an applicant's submissions against their OWN prior-cycle submissions (see gaps).

**A7 — Failure modes (as stated by sources).** Generic/recycled content (Erasmus Mundus, CSC); duplicate/ineligible course choices (Chevening: "Applicants who enter duplicate courses at the same universities cannot be considered for a scholarship"); exceeding length or wrong template (SISGP disqualification); unsupported claims (Australia GS: "We give more weight to statements supported by evidence"); AI-generated content (Chevening disqualification); fabricated achievements (Cambridge treats hallucinated personal claims as application fraud).

**A8 — Language requirements.** Chevening, Australia GS, and Fulbright require English; SISGP requires the application in English. Continental programmes taught in the local language may require the letter in that language, and French is required for certain French-taught Eiffel programmes (confirm per-programme — see gaps).

**A9 — AI-use and third-party-authorship policy.**
- **Chevening (verbatim):** "Using artificial intelligence software to generate answers to Chevening's essay questions is strictly prohibited… Chevening uses tools to detect fraud, plagiarism, and AI-generated content in applications. You will be asked to confirm that you have not used artificial intelligence to generate your answers as part of the application form." Chevening also states applicants "do not need to pay anyone to apply, and Chevening does not endorse or work with third parties who charge for application support."
- **Oxford (graduate, verbatim):** "The candidate may use AI tools to assist in researching application materials, but any submitted documents must be written by the candidate, and any text that is not the candidate's own should be appropriately referenced." Departments may screen supporting statements for plagiarism/AI.
- **Cambridge:** signatory to the Russell Group principles; permits AI for personal study/research but warns against using it to draft application documents, and states hallucinated personal claims "will be treated like any other application fraud."
- **DAAD, Erasmus Mundus/EACEA, Fulbright, SISGP, Rhodes, Australia Awards, Commonwealth Scholarship Commission:** **no specific published AI-authorship policy for the motivation letter was found** in this research. Report as "no published policy found," NOT as permission.

**A10 — Craft (guidance, not requirement).** Skilled writers build a through-line by tying past experience → present fit → future goal into a single argument. The MIT EECS Communication Lab (a named university resource) frames it as telling "your unique research story, not your life story," with personal detail admitted only in service of the research narrative. A letter reads as authored (rather than an assembled list of achievements) when each achievement is subordinated to a stated purpose and the paragraphs form one argument. All of this is craft guidance, not a rule.

### Track B — open-source solutions

**CV data schemas.** JSON Resume is a genuine community standard released under the MIT license, with a stable schema (basics/work/education/skills/projects) and an ecosystem of converters, themes and renderers — a real standard with adoption, not one person's repo. Europass European Learning Model (ELM) is the EU's authoritative model — JSON-LD extending the W3C Verifiable Credentials data model, now available in JSON Schema via the Publications Office (EDC profile), with 500+ properties; it is credentialing-oriented and heavy for CV authoring. Reactive Resume publishes its own schema (aspirational, single-project). HR-Open exists but is enterprise-HR oriented.

**CV renderers.** RenderCV (MIT) turns YAML/JSON into typeset PDF, is version-controllable, ships a published JSON Schema and an auto-generated AI-agent "skill," and delivers strong typography and text-layer quality. Reactive Resume and OpenResume are web-app builders. None guarantees a funder's fixed template out of the box (e.g., the SISGP PDF form) — that requires a custom template.

**Europass tooling.** The EU publishes the official ELM schema and the EDC infrastructure (free, GDPR-compliant credential issuance) in JSON-LD; the older Europass CV JSON/XML (v3.x) schemas are archived. There is no single lightweight official "produce-a-valid-Europass-CV" library for the current model.

**Document extraction / OCR.** Docling (Apache-2.0) — typed DoclingDocument, native DOCX/PPTX, good for structured downstream use. MinerU — moved from AGPLv3 to a custom "MinerU Open Source License" based on Apache 2.0 that "explicitly permits commercial use, modification, and distribution," strong on formulas/multi-column layouts. Marker — model weights under a modified OpenRAIL-M license requiring a paid commercial license for organizations above a revenue/funding threshold. Unstructured (Apache-2.0) — broad partitioning across many file types. License triage is essential.

**Motivation-letter/SOP generators.** As expected, thin: mostly paid SaaS (GradPilot and various "SOP writer" tools) and prompt collections, with little open-source substance encoding real domain rules. The best of it is generic and not a reusable rules engine.

**Agent skills / prompt libraries.** RenderCV ships an official agent "skill" for CV building that encodes real domain rules (auto-generated from its source and validated against its Pydantic pipeline). Admissions-essay prompt repositories are mostly generic advice.

**Taxonomies to consume.** ISCED-F 2013 (UNESCO Institute for Statistics): per ESCO, "The classification is designed as a three level hierarchy. There are 11 broad fields, 29 narrow fields and about 80 detailed fields"; used by ESCO to structure knowledge concepts; freely available. ESCO (EU): skills/competences/occupations, multilingual, machine-readable, free. Both are adopt-not-invent.

## Recommendations (staged)
1. **Adopt now:** JSON Resume as the internal CV data model; RenderCV as the default renderer; ISCED-F for programme-discipline classification and ESCO for skills. Build a **document-KIND router** that branches on {university motivation letter/SOP, funder multi-question form, study/research plan, immigration statement} — because each needs different input data.
2. **Build a per-target rules table** keyed to funder/university with hard limits (words/characters/pages/template/language) and binding-vs-advisory flags; seed from the CSV below. *Threshold to expand:* any target whose limits are not confirmed from a T1 source is flagged for counselor verification before the document is generated.
3. **Immigration guardrail (non-negotiable):** for Australia GS and Canada LOE, hard-block any workflow that could fabricate facts; require applicant-attested inputs and surface a legal-consequence (misrepresentation) warning.
4. **AI-policy gating:** where a funder prohibits AI-generated content (Chevening) or requires own-work (Oxford/Cambridge), operate in an assist-only/coaching mode and log provenance. Where policy is silent, default to conservative assist-only. *Change trigger:* if a named funder publishes an explicit permissive or prohibitive AI policy, update the gate for that funder.
5. **License triage for extraction:** prefer Docling (Apache-2.0) as the default transcript/CV parser; treat MinerU as adoptable under its new license (watch the attribution clause); avoid Marker weights above the revenue threshold unless licensed.

## Caveats
- Several funder length limits are widely repeated by coaching sites but not confirmed from the funder's own current-cycle page in this research (flagged in gaps). The Chevening per-essay word count in particular could not be confirmed on Chevening's own public guidance and should not be asserted as 500 without verification.
- Guidance changes by cycle; verify each source against the live current-cycle page before shipping rules.
- The SISGP official page blocked automated fetching in this research; SISGP details come from official-page snippets and archived form files, and the exact 2026/2027 form questions/limits should be re-verified.

---

## Track A — CSV ruleset

```
"ID","Rule","Applies to","Scope","Binding or advisory","Source (tier)","Source URL [provenance]","Verified for cycle","Confidence"
"L-001","Provide two separate documents — a Statement of Purpose (academic fit, research interests, career goals) and a Personal History Statement (background/life experiences) — and do not duplicate content between them.","structure","United States (UC Berkeley)","Binding","T1","https://grad.berkeley.edu/admissions/apply/statement-purpose [official]","evergreen","high"
"L-002","Keep the US graduate SOP academically focused; it is not a personal essay.","structure","United States (Cornell)","Advisory","T1","https://gradschool.cornell.edu/inclusion/recruitment/prospective-students/writing-your-statement-of-purpose/ [official]","2025","high"
"L-003","Do not treat the UK master's personal statement as the UCAS undergraduate statement; write it to the department.","structure","United Kingdom","Advisory","T2","UK university postgraduate admissions guidance","evergreen","medium"
"L-004","Write the DAAD letter of motivation on no fewer than one and no more than three pages; DAAD provides no sample.","length","DAAD","Binding","T1","https://www.daad.de/en/studying-in-germany/scholarships/information-for-scholarship-applicants/ [official]","evergreen","medium"
"L-005","Use a reflective and factual style; avoid platitudes, flowery phrases and flattery in the German motivation letter.","structure","Germany (Goettingen/DAAD)","Advisory","T1","https://www.uni-goettingen.de/en/648936.html [official]","evergreen","high"
"L-006","Submit a separate study plan / research proposal of no less than 200 words for the Chinese Government Scholarship.","length","China Scholarship Council","Binding","T1","Regulations on the Management of Chinese Government Scholarship [official]","evergreen","medium"
"L-007","Provide a MEXT Field of Study and Research Program Plan as a distinct form limited to 2 pages (embassy format), covering research background, topic, goals and timeline.","length","Japan (MEXT)","Binding","T1","MEXT embassy-recommended application form [official]","2023","medium"
"L-008","Submit both a GKS Personal Statement (Form 2) and a GKS Study Plan (Form 3), each answering a different brief.","structure","South Korea (GKS/NIIED)","Binding","T1","NIIED GKS application forms [official]","2026","medium"
"L-009","Write the Turkiye Burslari letter of intent directly in the online portal within its character limit.","length","Turkiye Burslari","Binding","T1","https://www.turkiyeburslari.gov.tr/evaluationandselectionprocess [official]","evergreen","medium"
"L-010","Answer the Genuine Student questions in the online visa form, 150 words each, in English; prefer in-form answers over an attached statement.","length","Australia (Home Affairs GS)","Binding","T1","https://immi.homeaffairs.gov.au/visas/getting-a-visa/visa-listing/student-500/genuine-student-requirement [official]","2024-cycle onward","high"
"L-011","Treat the Australian GS response as an immigration statement and support claims with evidence; more weight is given to evidenced statements, and a false statement risks a misrepresentation finding.","validation-flag","Australia (Home Affairs GS)","Binding","T1","https://immi.homeaffairs.gov.au/.../genuine-student-requirement + Ministerial Direction No. 106 [official]","2026","high"
"L-012","Attach a letter of explanation/study plan to the Canadian study permit application; IRCC lists it as recommended, addressing intent, ties and funding, and it is an immigration document.","structure","Canada (IRCC study permit)","Advisory","T1","IRCC 'Study permit: Get the right documents' [official]","2026","high"
"L-013","Answer all four required Chevening essays; verify the current per-essay word limit against Chevening's own application form before drafting.","length","Chevening","Binding","T1","https://www.chevening.org/resource-hub/guidance/application-criteria/ [official]","re-verify per cycle","medium"
"L-014","Do not use AI software to generate Chevening essay answers; submit own original work and attest to it; Chevening runs AI/plagiarism detection.","ai-policy","Chevening","Binding","T1","https://www.chevening.org/faqs/can-i-use-ai-to-help-me-write-my-application/ [official]","evergreen","high"
"L-015","Select three different eligible courses; entering duplicate courses makes you ineligible for a Chevening scholarship.","validation-flag","Chevening","Binding","T1","https://www.chevening.org/resource-hub/guidance/common-errors/ [official]","evergreen","high"
"L-016","Use the mandatory SISGP motivation-letter form and CV template (CV max 3 pages); wrong format or over-length disqualifies the application.","length","Swedish Institute (SISGP)","Binding","T1","https://si.se SISGP motivation-letter form [official]","2021-2022 form; re-verify","medium"
"L-017","Limit each Fulbright Foreign Student essay to 600 words / 1-1.5 pages, never exceeding two pages.","length","Fulbright Foreign Student","Binding","T1","Fulbright Foreign Student Program 2026-27 Slate Instructions PDF [official]","2026-27","high"
"L-018","Do not name specific US universities in the Fulbright personal statement.","prompt","Fulbright Foreign Student","Binding","T1","Fulbright Foreign Student Program instructions PDF [official]","2026-27","high"
"L-019","For Oxford graduate applications, submitted documents must be written by the candidate; AI may assist only with research.","ai-policy","University of Oxford","Binding","T1","https://www.ox.ac.uk/admissions/graduate/application-guide/applicant-policies/plagiarism [official]","evergreen","high"
"L-020","Do not rely on AI to draft Cambridge application documents; hallucinated personal claims are treated as application fraud.","ai-policy","University of Cambridge","Advisory","T1","https://www.postgraduate.study.cam.ac.uk/apply/how/ai-postgraduate-applications [official]","evergreen","high"
"L-021","Tailor the Erasmus Mundus motivation letter to the specific consortium's multi-country structure; generic statements are a named weakness.","prompt","Erasmus Mundus","Advisory","T1","EACEA/EMJM webinar materials (europa.eu) [official]","2024","medium"
"L-022","Avoid a generic study plan that could apply to any country or university (CSC).","validation-flag","China Scholarship Council","Advisory","T2","university/agency guidance","evergreen","medium"
"L-023","Write funder documents in English where the funder requires it (Chevening, Australia GS, Fulbright, SISGP).","language","multiple funders","Binding","T1","respective funder pages [official]","2026","high"
"L-024","Where a funder publishes no AI policy for the motivation letter (DAAD, Erasmus Mundus/EACEA, Fulbright, SISGP, Rhodes, Australia Awards, CSC, Commonwealth), default to assist-only; do not assume permission.","ai-policy","universal","Advisory","T2","no published policy found","2026","high"
"L-025","Gather research-specific source material (proposed topic, sometimes a named supervisor, and a timeline) before generating a CSC/MEXT/GKS study plan; it is a different document kind from a motivation letter.","structure","China/Japan/Korea study plans","Advisory","T1","CSC/MEXT/GKS official forms [official]","2026","high"
```

## Track B — table

| Project | URL | Licence | Maintained | What it does | Reuse vs rewrite | Verdict |
|---|---|---|---|---|---|---|
| JSON Resume | jsonresume.org/schema | MIT | Active (monorepo) | Community JSON CV schema | Adopt schema as internal model; rewrite nothing | **Adopt** |
| Europass ELM | europass.europa.eu | EU/open (JSON-LD, W3C VC) | Active (EU) | Authoritative EU learning/credential model + JSON Schema (EDC profile) | Reference for credential fields; too heavy as CV core | **Reference only** |
| RenderCV | github.com/rendercv/rendercv | MIT | Active | YAML/JSON → typeset PDF + JSON Schema + agent skill | Adopt as renderer; author custom templates for funder forms | **Adopt** |
| Reactive Resume | github.com/AmruthPillai/Reactive-Resume | Open source (self-host) | Active | Web resume builder + own schema | Reference schema/UX; not a library | **Reference only** |
| OpenResume | open-resume.com | Open source | Active | Web resume builder/parser | Reference only | **Reference only** |
| Docling | github.com/docling-project/docling | Apache-2.0 | Active | Doc parsing → typed DoclingDocument | Adopt as default transcript/CV parser | **Adopt** |
| MinerU | github.com/opendatalab/MinerU | MinerU OSS License (Apache-2.0 based) | Active | High-accuracy PDF/DOCX/PPTX parsing | Adapt for complex transcripts; check attribution clause | **Adapt** |
| Marker | github.com/datalab-to/marker | Weights: modified OpenRAIL-M | Active | Fast PDF→Markdown/JSON | Reference only unless licensed above revenue threshold | **Reference only** |
| Unstructured | github.com/Unstructured-IO/unstructured | Apache-2.0 | Active | Broad document partitioning | Adapt for ingestion | **Adapt** |
| ISCED-F 2013 | uis.unesco.org | Free (UNESCO) | Stable | Field-of-education taxonomy (11 broad / 29 narrow / ~80 detailed) | Adopt for programme classification | **Adopt** |
| ESCO | esco.ec.europa.eu | Free (EU) | Active | Skills/competences/occupations taxonomy | Adopt for skills tagging | **Adopt** |

**Prose verdict.** Three things are genuinely worth adopting. **JSON Resume** provides a mature, MIT-licensed CV data model, so there is no reason to invent a schema. **RenderCV** (MIT) is the strongest reusable renderer — text-layer PDF output, version-controllable, a published JSON Schema and an official agent skill — with the one caveat that funder-fixed templates (e.g., the SISGP form) must be authored custom. **ISCED-F + ESCO** are free, machine-readable taxonomies to consume rather than build. For extraction, **Docling** (Apache-2.0) is the safe default; **MinerU** is now commercially adoptable under its new license; **Marker** carries OpenRAIL-M revenue thresholds and should be treated as reference-only unless licensed. The motivation-letter/SOP "generator" space offers nothing substantive to adopt — it is thin SaaS and prompt lists, so the domain rules (this report's CSV) are the asset to build in-house.

## Questions I could not answer from primary sources (and what would settle each)
1. **Exact current-cycle word/page/font limits** for Chevening (per-essay), Gates Cambridge, Rhodes, Eiffel, Holland Scholarship, Stipendium Hungaricum, Commonwealth, Swiss ESKAS, and GKS graduate Study Plan character limits — settle with each funder's official current-cycle application form/PDF (the online application itself, not guidance pages).
2. **Whether DAAD, Erasmus Mundus/EACEA, Fulbright, SISGP, Rhodes, Australia Awards, and the Commonwealth Scholarship Commission run AI-detection or prohibit AI for motivation letters** — settle with each funder's official application terms or a direct written query to the funder.
3. **Whether any admissions system runs similarity checks against an applicant's OWN prior-cycle submissions** — settle with UCAS and university admissions-integrity policy documents.
4. **The precise binding language requirement for specific French-taught Eiffel programmes** — settle with Campus France / Eiffel programme pages and the individual programme's admission page.
5. **Exact SISGP 2026/2027 motivation-letter form questions and character limits** — settle by fetching the current si.se form (which blocked automated access here) or contacting the Swedish Institute.
6. **Confirmation of MEXT and GKS current-cycle page limits from the ministries' own forms** (rather than specialist secondary sources) — settle by downloading the current official forms from MEXT/NIIED or the receiving university.