# Motivation-letter ruleset — Track A findings

Started 2026-08-22. Companion CSV: `letter-rules.csv` (71 rows, `L-` prefixed, same columns as
`cv-rules.csv`). Research plan: `2026-08-22-letter-research-prompt.md`. Track B (open-source
landscape) is in `2026-08-22-open-source-landscape.md`.

Status: **Track A complete for the three priority questions and A1–A10; Track B complete.**
Every row is tagged with how it was verified: `[fetched 2026-08-22]` = primary page or PDF read
directly (scrapling / curl + pdftotext); `[via perplexity_research|perplexity_ask 2026-08-22]` =
reported by the research tool with a primary URL but not re-fetched. High-stakes rows (anything
that changes a document kind, a hard limit on a major funder, or an AI/fraud policy) were fetched
directly; the rest are medium confidence by construction.

Method note: `perplexity_research` at the 10-minute MCP cap timed out on 4 of 9 broad calls and
hit a 429 rate limit twice; the narrower `perplexity_ask` calls all completed. Cost for the
session was ~$18. MCP_TOOL_TIMEOUT is now 30 min (takes effect on restart).

---

## Priority question 1 — are study plans a distinct document kind?

**Answer: it depends on the funder, and the three East-Asian schemes are three different shapes.**

| Scheme | Verdict | What the official form actually asks for | Source material the engine needs |
|---|---|---|---|
| **MEXT** (Japan, research students) | **Yes — distinct kind.** | Prescribed two-section form: *1. Past and present field of study*; *2. Research theme and plan in Japan* → *(1) Research theme*, *(2) Research plan*; "Specify particularly the ultimate goal(s) of your research". Max 2 pages, Japanese preferred, English accepted. Plagiarism/fraud found after selection cancels the award retroactively. (L-011–L-014) | A proposed research theme, a plan, and stated end goals. **No supervisor field, no timeline heading** — do not make those mandatory. University/supervisor contact happens *after* first screening, via the international office. |
| **GKS** (Korea, graduate) | **Yes as a separate document, no as a research proposal.** | Form 2 *Personal Statement* (motivation, education, experiences, influences, awards) **and** Form 3 *Study Plan* (*Language Study Plan*; *Goal of study & Study Plan*; *Future Plan after Study*). 6,000 Korean / 17,000 English chars each. NIIED FAQ: "at least describe the general direction and outlines of your study plans… study objectives in Korea and tangible plans during and after." Form 4 *Research Proposal* exists only for the Research Program track. (L-015–L-018) | Degree-study goals, a course-level plan, post-degree plan, **and a language-learning plan** — the only funder found that asks for one. No topic/supervisor/timeline. |
| **CSC** (China) | **No fixed kind — a university-overlay document.** | Central wording is just "A Study Plan or Research Proposal in Chinese or English", **minimum 800 words for postgraduates** (200 is the *undergraduate* floor — L-008 corrected). No headings prescribed. Receiving universities fold it into their own personal statement with their own floors: PKU 1,500 words incl. research plan; Zhejiang ≥1,500 words incl. study proposal; Fudan ≤1,500 Chinese / 5,000 English chars. Pre-admission document from the university is mandatory; a named supervisor is not. (L-008–L-010) | Whatever the receiving university's overlay asks; the central floor is the only central rule. |

Also in this class: **Swiss ESKAS** (motivation letter ≤2 pages **plus** a 5-page research proposal on the official form, with timeline and milestones — L-033) and **Fulbright** (a *Study/Research Objective* that must explain how the plan "fits in with your previous training and your future objectives", separate from a *Personal Statement* that is "a narrative… not a list of facts" — L-030).

**Design consequence.** A single `STUDY_PLAN` kind is wrong. The honest model is: the **prompt record** carries a structural kind (L-065) and a list of prompt archetypes (L-064); the document is generated against those. MEXT needs `RESEARCH_PLAN` source material (theme, plan, goals) that the fact ledger does not hold and the student must supply; GKS needs `LANGUAGE_PLAN`; CSC needs nothing beyond the university overlay plus a `min_words` floor.

## Priority question 2 — does narrative weight differ by system?

**Answer: the belief is half right, and the half that is right is about *which document* carries the story, not about countries.**

**US.** The admissions offices' own pages route narrative into a *separate* document and tell applicants to keep the SOP academic:

- Berkeley SOP: "don't spend a great deal of time on autobiography"; "Write technically, or in the style of your discipline. Faculty are the people who read these statements"; "pose a question, define a problem". The Personal History Statement takes background, barriers, service, and "should not duplicate the Statement of Purpose". (L-045, fetched)
- UCLA: Personal Statement must cover experiences "not described in your Statement of Purpose". (L-046, fetched)
- Michigan Rackham: Personal Statement "should be different from your Academic Statement of Purpose". (L-047, fetched)
- Cornell ASOP: "an academically focused essay, not necessarily a personal essay … keep the focus on your academic background and future potential". (L-069, fetched)
- Toronto Political Science: "Please do not make this an autobiography… what we really want to know is what interests you analytically." (L-048, fetched)

So "US rewards personal narrative" is true of the **PHS / Personal Statement**, and false of the **SOP**, which is closer to a European letter than the folk belief suggests.

**Europe / Nordics.** Published rubrics reward evidence-backed, programme-specific motivation, but almost every prompt asks for *both* fit and motive:

- Aalto: academic performance and relevance of prior studies are evaluated first and "motivation… does not compensate for low grades"; a missing letter means rejection without evaluation. (L-052, fetched, updated 21 Aug 2026)
- TUM Informatics: letter = 10/100 points, two equally weighted criteria — qualifications beyond undergraduate level, and the ability "to illustrate the connection between personal interests and the content of the degree program… with convincing arguments and examples". (L-050; the appendix URL now 404s — locate the FPSO PDF before relying on the numbers)
- LMU MCB: letter 60% + GPA 40% (EU applicants); Groningen selective MSc: motivation 40%; Helsinki rubrics 0–10 with most points on prior courses and research fit, <6 rejected; Oslo ICH: "Statement of purpose (up to 1 point)"; Aarhus: academic background 75% / other 25%. (L-051)
- KTH explicitly requests "an autobiography" alongside programme reasons (L-053, fetched) — a direct counterexample to "no narrative in the Nordics".
- DAAD's own craft sheet: "Deal with your topics in a reflective and factual way… Avoid all kind of platitudes, flowery phrases and flattery." (L-028, fetched)

**Conclusion for the engine.** Narrative weight is a property of the **prompt**, not the country. The through-line the engine writes must be **evidence-anchored** everywhere (a story that cannot be tied to courses, projects, or experience earns nothing in any published rubric), and the *amount* of personal background is governed by whether the prompt has a `PERSONAL_BACKGROUND` archetype (US PHS, Fulbright PS, Rhodes, GKS Form 2, Commonwealth) or not (US SOP, most European letters, MEXT). Where two documents are paired, **non-duplication is a binding rule** (Berkeley/UCLA/Rackham) and needs a gate.

## Priority question 3 — is reuse across programmes penalised?

**Answer: no published penalty for reuse as such; the penalties are for *generic* content and for breaching caps.** (L-060, L-061)

- **Similarity detection:** UCAS Copycatch screens "All UCAS Undergraduate and UCAS Conservatoire personal statements" — not master's. No UK university was found publishing Turnitin screening of postgraduate statements; Oxford's "departments may screen… using a plagiarism-detection system… can also be used to detect AI usage" is the only T1 found. No US graduate school, DAAD, EACEA consortium, Fulbright or universityadmissions.se similarity-screening statement found.
- **What is published instead:** one letter per programme naming it at the top (KTH; uni-assist "in bold print at the top… otherwise we will not be able to link your letter"); "a generic interest statement is insufficient" (TUM Physics); one letter ranking all courses (DAAD EPOS); the two US documents must not repeat each other; over-length is removed (Oxford), not considered (Mundus MAPP, UvA), or scored down (Leiden >10% over).

**Design consequence.** Core narrative + regenerated programme paragraphs is consistent with every rule found. The `WRONG_INSTITUTION` gate and a mandatory institution/programme header block (uni-assist) matter more than any anti-reuse concern. Add a **`DUPLICATES_PAIRED_DOCUMENT`** check when a prompt record pairs an SOP with a PHS/personal statement.

---

## A1 / A1b — what each destination actually requires

The full per-destination table is in the CSV (L-001–L-010, L-019–L-059). The cross-cutting facts:

1. **There is no national master's statement anywhere.** Every UK, German, Dutch, Nordic, Canadian, Singaporean and HK requirement found is institution- or programme-level; Sweden's portal, Mon Master, uni-assist and EACEA all defer to the programme. "Personal statement" vs "statement of purpose" is a programme naming choice, not a country one.
2. **A letter is often *not required*.** NTNU: "No, we do not require a motivation letter." Helsinki: do not attach unrequested documents. DTU: fill the SOP sheet inside the mandatory template, "should not upload a separate SOP". Chalmers: optional except named programmes. Wageningen: optional. (L-054) → `required_documents` must be resolved per programme; the engine must never default to producing a letter.
3. **Two documents that must differ** is a recurring shape: US SOP + PHS; Fulbright objective + personal; Rhodes personal + academic; GKS Form 2 + Form 3. (L-065)
4. **Immigration documents** are a separate class with legal consequences: Australia GS (L-001–L-007, L-059) and Canada's study-permit letter of explanation (L-058 — recommended not mandatory, but misrepresentation "by a representative acting on the applicant's behalf, with or without the applicant's knowledge" brings 5 years' inadmissibility, and a concealed "ghost" representative is itself misrepresentation).
5. **Things that are not written documents at all:** Invest Your Talent in Italy wants a one-minute video (L-036); Open Doors and SISGP keep their prompts inside the portal (L-066).

## A2 — structure

Structure is **prescribed only where the form is**: MEXT's two sections, GKS's three headings per form, Chevening/Gates/Australia Awards/Commonwealth question sets, Utrecht and Heidelberg templates, Stipendium Hungaricum's "introduction, substantive content, closing" letter format. Where a continuous letter is asked for, no office publishes a required section order; what they publish is a *content checklist* (UCL's seven areas; KTH's four; DAAD's a–d questions; Aalto's three bullets). The engine's `ParagraphRole` set is therefore a rendering convenience, and the binding unit is **"every listed content item / prompt question is answered"** — which is exactly the `PROMPT_REQUIREMENT_UNMET` gate. The one structural rule that is binding on its own is the **header block** naming institution and programme (uni-assist, KTH).

## A4 — limits (summary; every figure is in the CSV)

| Kind of limit | Examples |
|---|---|
| Hard character caps in a form | Australia GS 150 words × 5; Australia Awards 2,000 chars × 4 ("will not be considered"); Gates 1,400/1,400/2,100/2,100; GKS 6,000 KR / 17,000 EN; UCL 3,000; Edinburgh 3,500; Imperial 3,500/section; Campus France 2,500; Euroculture 5,000 |
| Word caps | Chevening (form-displayed; 100–300 reported, unverified); Commonwealth 200/100/250/100 + 500 + 500; Rhodes 1,000 + 450; KTH <500; Mundus MAPP 500; IMSISS 600; MAECI 500; UCLA PS 500; Rackham PS 500; Toronto 500; LMU MCB 600; TU Delft 200/100/200 |
| Page caps | MEXT 2; DAAD Study Scholarships 1–3; EPOS 2; Helmut-Schmidt 2; ESKAS 2 (+5 proposal); Heidelberg 1–2; TU Berlin 2; Eiffel 1–2; UCL 2 sides A4 12pt |
| **Floors** | CSC 800 words (postgraduate); Stipendium Hungaricum minimum 1 page TNR 12; PKU/ZJU 1,500 words |
| Font/format | UCL 12pt single-spaced; UCLA 12pt 1-inch; Hungary TNR 12; Heidelberg Arial 10 / 1.5; Aalto 11pt; EPOS hand-signed and dated |
| Consequence of over-length | Oxford: removed, application incomplete; Mundus MAPP / UvA: excess not considered; Leiden: >10% over blocks "Excellent" |

`constraints` needs `min_words`, `max_chars` (with/without spaces — GKS and Australia Awards say "including spaces"), `max_pages`, `font`, and `per_question` caps.

## A5 — prompt archetypes

Eleven recurring archetypes with funder mapping are in L-064; the structural kinds (short-answer set / continuous letter / two statements / prescribed research form / consortium-specific / video) in L-065. Funders using **several short answers** rather than a letter: Chevening, Australia Awards, Gates Cambridge, Commonwealth, Australia GS, and many Dutch/Swedish programme forms. The `prompt_question_signature` in the cluster key should be the **sorted archetype set**, not raw question text.

## A6 — reuse

See priority question 3.

## A7 — failure modes (as stated by the offices)

- **Over-length:** Oxford removes it and treats the application as incomplete (L-040); Mundus MAPP/UvA ignore the excess; Leiden scores it down (L-055).
- **Missing required item:** Aalto rejects without evaluation (L-052); GKS disqualifies for "errors, missing required documents, or providing false information" (L-018).
- **Unnecessary statement:** Oxford removes it (L-040); Helsinki says do not attach (L-054).
- **Generic content:** TUM Physics "a generic interest statement is insufficient"; DAAD "platitudes, flowery phrases and flattery"; Purdue "boilerplate essay" (L-028, L-061, L-062).
- **Wrong institution / unlinked letter:** uni-assist cannot route it (L-057); Purdue "the correct school's name" (L-062).
- **Eligibility slips that void the application before reading:** Chevening duplicate course choices, a non-English form, and "relying on AI tools to write your application" (L-068).
- **Repeating the CV / the paired document:** DAAD "Do not start… by repeating your CV" (L-028); Berkeley/UCLA/Rackham non-duplication (L-045–L-047).
- **False or unsupported claims:** Cambridge treats AI hallucinations about achievements as admissions fraud → withdrawal + 5-year bar, attributed to the applicant even when an agent did it (L-041, L-042); MEXT cancels retroactively (L-013); Home Affairs: refusal, cancellation, future restrictions, possible prosecution (L-059); IRCC: 5-year inadmissibility (L-058).
- **Wrong language:** Eiffel French-first; Campus France programme language; Australia GS English only (L-063).

## A8 — language

Per funder/programme, never per country (L-063). The prompt record must carry `document_language`, and the GKS case shows the cap itself depends on the language (6,000 vs 17,000 chars).

## A9 — AI-use and third-party policy (letters specifically)

| Class | Who | Wording |
|---|---|---|
| **PROHIBITS** | Cambridge | "AI must not be used when writing personal statements and CVs. This prohibition covers the use of AI to help your use of English." Hallucinated achievements = application fraud. (Research proposals: permitted with acknowledgement.) L-041 |
| | Oxford | AI-generated material is plagiarism; statement "must be entirely the applicant's own work"; departments may screen and the tool "can also be used to detect AI usage". L-040 |
| | Edinburgh | "asking someone else to write your statement or using AI apps such as ChatGPT could be considered fraud". L-039 |
| | Chevening | "strictly prohibited"; detection tools; negative attestation in the form (R-091/R-092); **and** "does not endorse or work with third parties who charge for application support" — L-021 |
| **REQUIRES DISCLOSURE** | Rhodes (May 2026) | Mentors "must not write or edit"; attestation of own work where "own work" = original experiences, thinking and judgment "even where AI tools might have supported expression"; disclose every helper and, for GenAI, the tool and prompts; AI must not generate substantive content. L-024 |
| | DAAD (page updated 6 Jul 2026) | AI "permitted as an aid"; passages must carry "Produced with the aid of (tool used)"; Declaration of Authenticity that the application "was prepared independently". L-025 |
| **IMMIGRATION PROHIBITION** | Australia Home Affairs (11 May 2026) | "Do not modify or create documents using… artificial intelligence (AI), or any other method." L-059 |
| **FRAUD CLAUSE ONLY** | MEXT (retroactive cancellation), GKS (false information → disqualification) | L-013, L-018 |
| **SILENT** (nothing found ≠ permission) | EACEA, Fulbright/IIE, SISGP, Gates Cambridge page, Australia Awards, Commonwealth CSC, Stipendium Hungaricum, Türkiye, CSC China | L-067 |

**Corrections to `cv-rules.csv`:** R-093 recorded "no AI policy located" for DAAD and Rhodes. Both now exist (L-024, L-025) and are the two *disclosure* regimes — the product's `ai_use_policy` reference data needs a third value beside prohibit/silent. R-093 and the CV ruleset's "Honest gap" paragraph were corrected on 2026-08-22 to point here.

**Design consequence.** The 2026-08-22 decision that `ai_use_policy` is reference data surfaced to the counselor, not a generation gate, now has to carry *three* classes plus the immigration class. For REQUIRES DISCLOSURE funders the counselor note should say what the disclosure text must be (DAAD's exact phrase; Rhodes' checkbox list). For Cambridge/Chevening the note must say that the destination's own wording covers English-language help and agency help, not only generation.

## A10 — craft (guidance, never requirement)

From DAAD's sheet (T1 guidance), Berkeley Career Center and Purdue OWL (T2):

- One unifying theme; past → present question → future trajectory; "show a progression" (Purdue).
- Evidence then interpretation: draw conclusions "from the evidence your life provides", document them with "specific instances"; a "catalog of achievements… tells nothing about you as a person" (Berkeley).
- The Stewart test: cut every sentence that "could have been written by anyone" (Purdue).
- Don't open with "I've always wanted to be a ___" (Berkeley); don't open by repeating the CV (DAAD).
- Reflective and factual; no platitudes, flattery or campaigning (DAAD).
- Some facts and figures about the home-country problem are "highly welcome" (DAAD) — i.e. `PROGRAMME_DERIVED`-style claims about context, which need a source.

These are prompt constraints for generation, alongside the humanizer patterns — not a rewrite pass.

---

## Consolidated design consequences for the §4.2 draft

1. **Document kinds.** Replace the single `MOTIVATION_LETTER` with a prompt-record-driven model: `ApplicationPrompt.structure ∈ {SHORT_ANSWER_SET, CONTINUOUS_LETTER, TWO_STATEMENTS, PRESCRIBED_RESEARCH_FORM}` and `archetypes: set[...]` (L-064/L-065). `CORE_NARRATIVE` stays. A `GS_FORM` is just a `SHORT_ANSWER_SET` with the immigration flag.
2. **New source-material kinds the ledger lacks:** research theme/plan/goals (MEXT, ESKAS, Fulbright objective); language-learning plan (GKS); home-country circumstances (Australia GS); development-impact outcomes/timeframe/beneficiaries/measurement (Commonwealth, Australia Awards). These are student-supplied, counselor-verified inputs, not `VerifiedFact`s.
3. **`constraints`:** add `min_words`, `max_chars_incl_spaces`, per-question caps, font. A floor cannot be satisfied by truncation — generation must target the floor.
4. **Gates to add:** `DUPLICATES_PAIRED_DOCUMENT` (US SOP/PHS, Fulbright, Rhodes, GKS); `HEADER_BLOCK_MISSING` for uni-assist/KTH routes; `LANGUAGE_MISMATCH`.
5. **Cluster key:** `prompt_question_signature` = sorted archetype set; `word_limit_band` must be per structure kind (a 2,000-char short answer and a 3-page letter never cluster).
6. **Immigration class:** Australia GS and Canada LoE get the existing anti-fabrication gate with *no* counselor override, and the AI-policy note quotes Home Affairs / IRCC.
7. **Not required is a first-class outcome:** the programme record needs `letter_required ∈ {required, optional, not_requested, unknown}`, failing closed to `unknown` → counselor item, mirroring `cv_format_requirement`.
8. **AI policy:** three classes + immigration (see A9).

## Reconciliation with the Compass deep-research report (2026-08-22)

A separate Claude deep-research run (`~/Desktop/compass_artifact_wf-255b094c-….md`, 25-row CSV) was compared against this ruleset. Adopted after direct fetch: Chevening common-errors flags (L-068), Cornell ASOP wording (L-069), Göttingen as corroboration of the DAAD advice sheet (L-028). Not adopted: MIT EECS CommLab "research story, not life story" (URL 404); Copenhagen "Focus on the study programme" (URL not given, redirect to a generic page); UPenn Career Services (T2). Where the two disagree this ruleset stands, because each Compass figure was superseded by a direct fetch here: CSC 200 words is the undergraduate floor (postgraduate 800, L-008); DAAD and Rhodes *do* publish AI policies (L-024/L-025, Compass L-024 is stale); Chevening "500 words" is as unverified as the 100–300 range recorded here. Compass's Track B verdict (adopt JSON Resume + RenderCV now) was made without sight of `render.py`; the landscape note's "reference only" verdict stands until a funder check fails on the current render path.

## Reconciliation with the Gemini deep-research report (2026-08-22)

A Gemini deep-research run (`~/Desktop/Master's Admissions and Tooling Research.md`, 23-row CSV) was compared the same way. Its CSV labels coaching sites, Scribd/Studocu uploads and US fellowship-office pages as "T1", so every figure was re-checked against what this ruleset fetched directly. Adopted after fetch: the Cambridge Applicant Portal character caps (L-070) and the Open Doors 2026 Rules wording (L-066 upgraded from perplexity lead to fetched). Stale or mis-attributed, this ruleset stands: Gates Cambridge "3,000 characters" is the old single statement (L-022 has the four-question caps from Gates' own page; the Cambridge FAQ still lists 3,000 — flagged in L-070); Gates "no assistance" attestation comes from a 2018 Arkansas PDF; Rhodes "no editorial feedback from anyone" is a Michigan constituency page — the Rhodes May 2026 PDF (L-024) says mentors must not *write or edit* and all help must be disclosed, which does not bar disclosed counselor feedback; Oxford's "cheating unless permitted" is the *student assessment* GenAI policy, not the admissions rule (L-019/L-040); GKS "2 pages, TNR 11" is the 2020 paper form — the 2026 online form caps at 6,000 KR / 17,000 EN characters (L-016); SISGP 1,000/1,200-character questions are the 2019–20 form (L-066); Chevening 100–500 words is from a coaching site and is no better verified than the range recorded here. Gemini's narrative-weight conclusion ("US rewards vulnerability") rests on the Berkeley PHS and a coaching blog; the per-document answer under Priority question 2 stands. Its gaps list (CSC, Hungary, Commonwealth, ESKAS, MAECI "no data") are all covered here. Track B: Gemini rates ELM v3 and Reactive Resume "Adopt" and calls Docling/Unstructured "open-core that restricts commercial use" — Docling is MIT and Unstructured Apache-2.0, so that claim is wrong; the landscape note's verdicts stand. One Gemini claim that *did* survive a spot-check of the primary page: Home Affairs states that a future intention to apply for permanent residence "does not count against an applicant under GS" (L-071) — Gemini cited a migration-agent blog for it, but the sentence is on the official page. Method rule carried forward: a secondary citation is a lead to fetch, never a reason to reject the claim.

## Questions still open, and what would settle them

| Question | What would settle it |
|---|---|
| Chevening's current per-answer word limit (100–300 reported) | Screenshot or export from the live 2027/28 application form |
| Türkiye Bursları letter-of-intent character limit (3,000 reported) | The authenticated TBBS form |
| SISGP 2026/27 motivation questions and limits | The live SI portal during the February window |
| TUM Informatics points table (URL 404) | The current FPSO PDF on the TUM CIT site |
| Commonwealth 2027/28 limits (figures are from the 2021 example form) | The live CSC application system after 8 Sep 2026 |
| Fulbright per-country page limits | Each commission's instructions; store per country, not per programme |
| Whether any university runs similarity checks across an applicant's *own* prior submissions | No source found; only a direct enquiry would settle it |
| CSC university overlays beyond PKU/ZJU/Fudan/Tsinghua | Per-university admissions pages, cycle-locked |
| Rackham's generative-AI guidance text (linked, page 404) | Find the moved page |
