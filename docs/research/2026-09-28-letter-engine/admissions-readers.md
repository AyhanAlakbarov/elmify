# Research notes: what makes a motivation letter / SOP succeed or fail (fetched 2026-09-28)

Method: WebSearch + WebFetch/scrapling; PDFs decoded locally with pdftotext. "Fetched" = primary page read
directly; "snippet" = only a search-result excerpt was available (host refused or blocked us).
DAAD hosts (daad.de, www2.daad.de) refused connections from this network all session; DAAD content below
comes from a DAAD sheet re-hosted by RPTU, and a search snippet of the DAAD applicant-information page.

Overlap: much of Q1/Q2 already lives in the repo's `docs/research/2026-09-14-letter-storytelling-evidence.md`
(§2.3 reader table) and `letter-rules.csv`. New here: the AI-policy map (Q3), the 2025-2026 outcome studies
(Q4), Oxford's over-length removal rule, Fulbright's "no universities" rule, Stipendium Hungaricum's
"not the actual applicant" clause.

---------------------------------------------------------------------------------------------------
## Q1. What readers say they reward / penalise (official guidance)

### DAAD
- "How to Write a Letter of Motivation" (DAAD sheet, Pakistan-office edition, undated, likely pre-2020),
  re-hosted: https://applymsc.cs.rptu.de/upload/DAAD-Letter_of_motivation.pdf (fetched, pdftotext)
  - "Regrettably, however, they often fail to convince any member of a selection committee."
  - "Do not start your letter of motivation by repeating your CV."
  - Questions: professional goal and sector; contribution to "social, political or technical development of
    your home country" ("Some facts and figures are highly welcome"); which courses of the programme are
    beneficial ("Make sure you are well informed!"); why you are the right person; why Germany.
  - "Emphasize your strong points, but be realistic."
  - "(Not all of the above questions have to be addressed!) Do not include the outline or the questions in your text."
  - "Avoid all kind of platitudes, flowery phrases and flattery." "Deal with your topics in a reflective and
    factual way. Do not campaign for your beliefs."
  - "not more than two or three pages"; "letter of motivation may be discussed with you during pre-selection interviews."
- DAAD applicant information page (snippet; direct fetch refused):
  https://www.daad.de/en/studying-in-germany/scholarships/information-for-scholarship-applicants/
  - AI use must be marked: "Produced with the aid of (tool used)"; declaration that the application was
    prepared independently; "Applicants' unique qualities and characteristics should remain evident".
    (Repo note 2026-09-14 records the same wording as fetched then: T1 FAQ B.3.)

### TUM (fetched) https://www.tum.de/en/studies/application/application-info-portal/document-requirements/tum-style-guide
- SOP "no longer than one page"; A4, Times New Roman/Arial 12pt, 2 cm margins, 1.5 spacing, PDF.
- Must answer 3 questions: Why this programme and TUM? How are you suited? Are you particularly motivated to complete it?
- "A generic letter of motivation is not sufficient."
- Generic salutation ("Dear Sir or Madam") is fine; name, surname, DOB, date of creation, document title on every document.
- Third-party content must be cited even in the SOP; "All self-created documents are checked for plagiarism by TUM."
- "The use of AI tools such as ChatGPT to create documents for an application at TUM is not permitted."
  "Self-created application documents are thoroughly checked for the use of AI." Detected -> "excluded from
  the application process, i.e. your application will be rejected for deception."
- (Exception: TUM Institute for LifeLong Learning EMBA guideline allows AI with disclosure of where/which/why:
  https://www.lll.tum.de/wp-content/uploads/2025/05/25_Guidelines_EMBAs_LetterOfMotivation_Essay.pdf — snippet only.)

### ETH Zurich (snippet) https://ethz.ch/en/studies/master/application/faq.html
- About one A4 page, in the language of instruction; interests, competences, motivation for this programme
  at ETH, expectations of teaching, future plans. Programme-specific rules vary. No public AI rule found.

### Oxford (fetched)
- https://www.ox.ac.uk/admissions/graduate/application-guide/supporting-documents/statement
  - "If your statement of purpose or personal statement significantly exceeds the permitted length stated
    on the relevant course page, it will be removed from your application and your application will be
    considered incomplete and is unlikely to be assessed by the academic department."
  - "must be entirely your own work. Departments may screen your statement of purpose or research proposal
    using plagiarism-detection software."
  - Criteria live on each course page ("the criteria by which they will be assessed").
- https://www.ox.ac.uk/admissions/graduate/application-guide/starting-your-application/using-artificial-intelligence-in-your-graduate-application
  - fetched lead: "AI may be used to assist in researching application materials, but the ideas and their
    expression must be yours. Using AI for beyond the permitted uses ... may disadvantage you in the assessment".
  - accordion bodies not served to us; snippet: not permitted = asking AI to write the statement, submitting
    AI text as your own, using AI to fabricate experiences; "Fabricating information ... may constitute fraud";
    disability-assistive tools permitted.

### Cambridge (fetched) https://www.postgraduate.study.cam.ac.uk/apply/how/ai-postgraduate-applications
- "AI must not be used when writing personal statements and CVs. This prohibition covers the use of AI to help your use of English."
- "AI may generate false claims ('hallucinations') and if these are about your personal achievements they
  will be treated like any other application fraud."

### LSE (fetched) https://www.lse.ac.uk/study-at-lse/Graduate/Prospective-students/Supporting-documents/Statement-of-academic-purpose
- 1,000-1,500 words usually; academic motivations (modules, faculty research), suitability, purpose/objectives.
- "Please avoid general statements about LSE's performance in global rankings, and generic statements about
  London being a global/cosmopolitan centre of excellence."
- Two programmes -> "strongly encouraged to write a separate statement for each programme."
- "Are all your own work. If we discover this is not the case, your application may be cancelled." (no AI clause)

### Chevening
- AI FAQ (fetched) https://www.chevening.org/faqs/can-i-use-ai-to-help-me-write-my-application/
  "Using artificial intelligence software to generate answers to Chevening's essay questions is strictly
  prohibited." "Chevening uses tools to detect fraud, plagiarism, and AI-generated content in applications."
  Disqualification; applicants attest they did not use AI.
- Application criteria (fetched, current) https://www.chevening.org/resource-hub/guidance/application-criteria/
  four areas: leadership/influencing with "clear results"; networking with "real, measurable outcomes";
  course choice linked to UK priorities and "specific modules"; "short, mid, and long-term career plan which
  has clear, measurable goals". "assessed against your ability to answer questions in each of these four areas".
- Application advice (fetched, dated 25 May 2021 — older) https://www.chevening.org/news/application-advice/
  "Use 'I' instead of 'we'"; examples from employment/voluntary work rather than school; "Don't use bullet
  points"; "Assessors know when answers are copied and pasted from a CV, personal statement or reference
  letter"; one or two detailed stories beat many brief ones; research modules/professors; don't copy
  institutional websites.
- Word limit: 100-300 words per essay since 2026/27 (secondary: IDS blog
  https://www.ids.ac.uk/opinions/want-to-win-chevening-five-tips-to-nail-your-essays-even-in-300-words/ ;
  Chevening itself only shows limits inside the form).

### Fulbright Foreign Student Program (IIE guideline, Nov 2019, re-posted by commissions incl. 2025)
- https://fulbright.se/documents/14/Essay_Guidelines.pdf (fetched, pdftotext); same text at
  https://lt.usembassy.gov/wp-content/uploads/sites/209/2025/02/Fulbright-Essay-Guidelines.pdf (403 to us)
  - Study objective: "clear and very detailed description"; relevance to "current trends/challenges in your
    home country"; "How will you apply your studies upon returning"; "References to proposed universities or
    faculty should not be made."; 1-2 pages; "Please use your own words".
  - Personal statement: who you are, experiences/people/events that inspired, contribution, 1-2 pages.
- USEF Nepal: no blanket Fulbright AI rule; "cite AI-generated content if applicable" https://usefnepal.org/fulbright/ffsp/plagiarism/

### Türkiye Bursları (fetched)
- https://www.turkiyeburslari.gov.tr/evaluationandselectionprocess — criteria "academic status, previous
  qualifications, academic interests, career goals, consistency of preferences, content of the letter of
  intent, and participation in social activities"; interview 15-30 min covering application purpose.
- https://www.turkiyeburslari.gov.tr/sayfa/mastering-the-application-insider-tips-for-turkiye-scholarships-82
  "align your statement with scholarship program goals", authentic, concrete examples, address prompts.
- Letter of intent written into portal with a character limit; any language (secondary: catchthatscholarship).

### Stipendium Hungaricum 2026/27 Call (fetched, pdftotext)
https://stipendiumhungaricum.hu/wp-content/uploads/2025/10/BA_MA_OTM_Call_for_Applications_2026_27.pdf
- Motivation letter: "minimum 1 page, typed in Times New Roman 12-point letters", "written in the language of
  the selected study programme or Hungarian".
- Rejected if applicants "provide false information" or "are not the actual applicant (the application was
  submitted by someone else)".

### GKS (NIIED 2026 GKS-G guideline, mirror of official PDF, fetched)
https://gksscholarship.com/wp-content/uploads/2026/02/2026-GKS-G-Application-Guidelines-English.pdf
- Form 2 Personal Statement + Form 3 Study Plan required. FAQ: study plan must give "general direction and
  outlines" and "study objectives in Korea and tangible plans during and after".
- Competency judged by document examination and interview; "Authenticity Check: ... NIIED may inquire about
  the facts"; disqualification for "providing false information".

### MEXT 2027 research guideline (fetched, pdftotext)
https://www.studyinjapan.go.jp/en/_mt/2026/04/01-2027_Research_Guidelines_E.pdf
- Documents must "state the applicant's research plan in a detailed and concrete manner"; interview must
  show "a clear sense of purpose relating to his/her study in Japan and has gathered information about
  Japanese universities"; provisional acceptance letter from a Japanese university "will greatly influence
  final selection results" (supervisor-led step).

### CSC (China) — embassy notice (snippet) https://id.china-embassy.gov.cn/eng/sgdt/202510/t20251027_11741674.htm
- Study plan / research proposal in Chinese or English, >=800 words for postgraduates.

### Swedish Institute SISGP (si.se 403 to us; snippets)
- Must use SI's motivation-letter form; assessed on professional experience, leadership, motivation linked
  to sustainable development / home country. https://si.se/en/apply/scholarships/swedish-institute-scholarships-for-global-professionals/

### Erasmus Mundus
- No EACEA-wide letter rubric: each consortium sets criteria. Example: EMJM Emergency & Critical Care Nursing
  scores academic 50%, experience 25%, interview 25% with motivation judged in the interview
  (https://masternursing.emjmd.eu/admission/selection, fetched). Other consortia score the letter directly
  (secondary sources claim ~15 points of 100 on some grids).

### US
- Berkeley (fetched) https://grad.berkeley.edu/admissions/application-process/writing-your-statements/
  SOP + separate Personal History Statement ("should not duplicate"); "Write technically, or in the style of
  your discipline. Faculty are the people who read these statements."; "500 to 1,000 well-selected words".
- Cornell (fetched) https://gradschool.cornell.edu/admissions/application-steps/important-application-policies/use-of-generative-ai-in-graduate-admissions-applications/
- Caltech SOP packet https://sfp.caltech.edu/documents/20201/SOP_Packet_fillable_FUTURE.pdf (fetched):
  origin stories — "readers skim or skip such stories"; illustrative (not measured) "about 5 minutes per application".

### How readers evaluate
- Isley, Gaebler, Goel (arXiv 2609.22549, Sept 2026) — see Q4 — 5 admissions staff rated 100 essays.
- Appleby & Appleby 2006 (older), survey of psychology grad admissions chairs: "kisses of death" = damaging
  personal statements (excessive self-disclosure, excessive altruism), lack of program information, poor writing,
  misfired attempts to impress. https://journals.sagepub.com/doi/10.1207/s15328023top3301_5
- Rubric-based holistic review (Young et al. 2021/22, physics): 18 metrics incl. research experience,
  noncognitive competencies, fit. https://arxiv.org/abs/2110.04329
- No rigorous measurement of reading time per graduate statement found; figures online are anecdotal
  (undergrad "8-minute" claims from consultancies — not used).

---------------------------------------------------------------------------------------------------
## Q2. Reader type and country convention (synthesis of the above)
- Scholarship funder: impact/return story — DAAD home-country development; Chevening leadership, networking,
  UK-collaboration career plan; Fulbright home-country relevance and "applying studies upon returning", no
  university names; SISGP leadership + sustainable development; Türkiye "consistency of preferences".
- Programme admission committee: fit + readiness + specificity — TUM 3 questions, LSE academic motivation and
  modules, ETH competences/expectations, Oxford course-page criteria, Berkeley discipline register.
- Supervisor-led: research plan feasibility and a named host — MEXT detailed concrete research plan +
  provisional acceptance; CSC >=800-word proposal + pre-admission; GKS study plan; Berkeley research-question detail.
- Format by country: DE/CH one page (TUM, ETH), letter-ish header allowed, generic salutation; HU min 1 page
  TNR 12; UK 1,000-1,500 words (LSE), hard length (Oxford removal); Chevening 4 x 100-300 words; US 500-1,000
  words, two statements; JP/KR/CN prescribed forms; TR/RU portal text fields (Open Doors: typed into form per
  profile, https://od.globaluni.ru/rules).
- Tone: DAAD "reflective and factual", "strong points, but be realistic", no campaigning; Chevening "I" not "we",
  measurable results (Anglo self-promotion). Cross-cultural genre study of 100 Chinese applicants' SoPs:
  "self-critique" of home-country issues "may not be an appropriate rhetorical choice for self-promotional
  writing in Anglo-American tradition" (Functional Linguistics 2017, older)
  https://link.springer.com/article/10.1186/s40554-017-0041-9
- Gulf states and Russia: no official letter guidance found beyond Open Doors form rules (gap).

---------------------------------------------------------------------------------------------------
## Q3. AI rules and detection (2024-2026)
- Prohibit: TUM (with AI checking, rejection for deception); Cambridge PG (incl. English help); Chevening
  (detection tools + attestation); Columbia GSAS/SIPA/Law etc. (secondary: https://gradpilot.com/ai-policies/columbia-university);
  UCAS forbids generating "all or a large part" (https://www.ucas.com/applying/applying-to-university/writing-your-personal-statement/a-guide-to-using-ai-and-chatgpt-with-your-personal-statement).
- Limited use, penalised beyond: Oxford ("may disadvantage you"; fabrication = fraud).
- Allow with disclosure: DAAD ("Produced with the aid of (tool used)"); Cornell (disclose any use, even
  grammar; drafting/outlining prohibited); TUM EMBA only.
- Silent/"own work": LSE; Fulbright defers to universities; ETH no public rule found; Stipendium Hungaricum
  forbids "not the actual applicant".
- US undergrad landscape: Kaplan survey Jul-Aug 2025 (n=220): 2% allow AI for writing essays, 30% ban, 68% no
  policy; 50% of officers unfavourable. https://kaplan.com/about/press-media/college-admissions-officers-survey-2025-essays-ai
- Detection: UCAS Copycatch = similarity, not AI; library of past statements + web samples; >=30% reviewed
  (Loughborough https://www.lboro.ac.uk/study/apply/support/ucas-similarity-detection/ ; UCAS guide
  https://www.ucas.com/sites/default/files/similarity-detection-applicant-guide.pdf). Oxford plagiarism
  software; TUM AI check (tool unnamed); Chevening "tools".
- Turnitin (Mar 2023): claims <1% false positive; "false positive rate is not zero ... apply your professional
  judgment". https://www.turnitin.com/blog/understanding-false-positives-within-our-ai-writing-detection-capabilities
- Non-native bias: Liang et al. 2023 (Patterns): 7 detectors flagged 61.3% of TOEFL essays as AI, near-zero
  for US 8th-graders; one flagged ~98%. https://www.cell.com/patterns/fulltext/S2666-3899(23)00130-7
  Counter-evidence: ETS/Jiang et al. 2024 (Computers & Education) purpose-trained detector ~99% accurate,
  slightly HIGHER false positives on native samples https://www.sciencedirect.com/science/article/abs/pii/S0360131524000848 ;
  Al Ali et al. EACL-SRW 2026, Czech: no systematic bias; modern detectors don't rely on perplexity
  https://arxiv.org/abs/2602.05769 . Net: bias is detector-specific; commercial perplexity-style detectors
  were biased; the risk for our population is real but not universal.

---------------------------------------------------------------------------------------------------
## Q4. LLM-written application essays
- Isley, Gaebler, Goel, arXiv 2609.22549 (18 Sep 2026): ~7,500 applications 2020-2025 to a large US public
  policy master's; 2025: 56% submitted >=1 primarily AI essay (69.3% international vs 38.6% domestic);
  GPTZero, 0.8% false positive pre-ChatGPT; ~1.5 pp lower admission per AI-flagged essay (3.48 pp for typical
  user); staff AUC 0.70 at spotting AI; essays staff deemed "very likely" AI scored markedly lower even
  adjusting for quality; AI raised grammar/clarity but less voice/commitment/leadership.
  https://arxiv.org/abs/2609.22549 , https://arxiv.org/html/2609.22549v1
- Lee, Borchers, Alvero, Joachims, Kizilcec (L@S 2026, arXiv 2602.17791): 81,663 applications to a selective
  US university 2020-2024; LLM use higher among lower-SES; surface features converged post-2023; LLM use
  associated with lower admission odds, steeper for lower-SES (beta -1.78 vs -0.96). https://arxiv.org/html/2602.17791
- Moon, Green, Kushlev (2025): 2,200 admissions essays; human essays add 2-8x more collective semantic
  diversity than GPT-4 essays; persisted after prompt/parameter tweaks.
  https://www.sciencedirect.com/science/article/pii/S294988212500091X (snippet; 403 to us)
- "Impersonal Statements" / paradoxical homogenization (PsyArXiv, 2025): >160k (and 372,793 across four
  universities) essays: post-ChatGPT higher lexical diversity but lower idea and thematic distinctiveness,
  disproportionately among linguistic minorities. https://osf.io/preprints/psyarxiv/jsz58_v6
- Cover-letter signal collapse: Cui, Dias, Ye (arXiv 2509.25054, 2025): AI tool raised job-post alignment and
  callbacks but alignment-callback correlation fell 51%; editing time of AI drafts correlated with hiring.
  https://arxiv.org/abs/2509.25054 . Galdin & Silbert (2025) Freelancer.com: employers stopped paying for
  customization after LLMs. https://arxiv.org/abs/2511.08785
- Residency personal statements: readers often cannot tell (anesthesia PDs: >90% acceptable, 80% could not
  distinguish; https://www.sciencedirect.com/science/article/pii/S0952818023001356 ; orthopaedics 2025
  https://pubmed.ncbi.nlm.nih.gov/42005879/ ).
- AI tells: Reinhart et al. PNAS 2025 — instruction-tuned LLMs use present participial clauses 2-5x (GPT-4o
  5.3x) and nominalizations 1.5-2x human rates https://www.pnas.org/doi/10.1073/pnas.2422455122 ;
  Kobak et al. Science Advances 2025 excess vocabulary ("delve" etc.), >=13.5% of 2024 abstracts
  https://www.science.org/doi/10.1126/sciadv.adt3813 ; Wikipedia "Signs of AI writing": promotional tone,
  inflated significance, rule of three, formulaic transitions https://en.wikipedia.org/wiki/Wikipedia:Signs_of_AI_writing ;
  Kaplan officer quote: writing "doesn't match the writing of other sections".
- Disclosure penalty: Schilke & Reimann, OBHDP 2025, 13 experiments — disclosers trusted less.
  https://www.sciencedirect.com/science/article/pii/S0749597825000172

---------------------------------------------------------------------------------------------------
## Q5. Failure modes (each sourced)
1. Generic letter — TUM "A generic letter of motivation is not sufficient"; LSE separate statements.
2. Rankings/city/flattery filler — LSE rankings/London clause; DAAD "flattery".
3. Over length — Oxford removal -> "unlikely to be assessed"; Chevening/portal hard caps.
4. Repeating the CV — DAAD "Do not start ... by repeating your CV"; Chevening copy-paste from CV.
5. Claims without evidence — Chevening "Stating that you have the required skills is not enough" (resource hub,
   snippet) and "clear results"/"measurable".
6. Not answering the set questions — TUM 3 questions; Chevening "assessed against your ability to answer
   questions in each of these four areas"; GKS form confusion.
7. Fabrication/hallucination — Cambridge fraud; Oxford fraud; GKS/Stipendium false-information disqualification.
8. Detectably AI-written — TUM rejection; Chevening disqualification; Isley et al. penalty.
9. Wrong rules for the reader — Fulbright forbids naming universities; Berkeley PHS must not duplicate SOP;
   language of letter (Stipendium, ETH).
10. Poor writing / wrong register / oversharing — Appleby & Appleby; Berkeley "style of your discipline";
    Caltech: origin stories skimmed.
11. "We" instead of "I" / group credit — Chevening.
12. Letter the applicant cannot defend in interview — DAAD pre-selection interviews; Türkiye interview on purpose;
    MEXT interview.
Wrong university name: only secondary sources (admissions consultancies) found — no primary source.
