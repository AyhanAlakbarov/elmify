# Official Graduate Admissions and Scholarship Funder Guidance on Reference Letters

**Date:** 2026-11-02  
**Scope:** Primary-source investigation of official referee/recommendation instructions across UK universities (Oxford, Cambridge, LSE, Imperial), continental European universities (ETH Zurich, TUM, KU Leuven, Leiden, TU Delft), and major scholarship funders (DAAD, Chevening, Fulbright, Gates Cambridge, Rhodes, Erasmus Mundus, Stipendium Hungaricum, Global Korea Scholarship).

## Search & Verification Methodology

- **Search services used and missing:** `Exa` was unavailable in this session (`401: Invalid API key`). `Context7` applies to software libraries and was not applicable. `Tavily` was not required. Candidate and owner-domain searches were executed via `search_web` and `brave-search` (`brave_web_search`).
- **Page fetching and verification:** Every cited HTML page was fetched directly from its official domain via `scrapling` (`get` / `bulk_get`) and `read_url_content` (`ox.ac.uk` blocked `read_url_content` with HTTP 403 and was retrieved via `scrapling` `get`/`bulk_get`). Official PDF forms and calls for applications (`cit.tum.de`, `rhodeshouse.ox.ac.uk`, `stipendiumhungaricum.hu`) were inspected directly via `view_file`.

---

## Narrowed Sub-Questions

1. **Sub-Question 1 (Evaluation Criteria & Required Content):** What specific questions, evaluation dimensions, cohort rankings/percentiles, and programme-suitability assessments do official UK/European graduate admissions pages and major scholarship funders ask referees to address?
2. **Sub-Question 2 (Academic vs. Professional Referee Rules):** When do universities and funders permit or require a professional/employer referee versus an academic referee, and how do the evaluation prompts differ between the two?
3. **Sub-Question 3 (Authorship, Confidentiality, Portal Attestations & Formatting Formalities):** Which institutions enforce confidential referee-only portal submission (banning applicant uploads or third-party editing/AI drafting) versus applicant-uploaded letters, and what formatting rules apply (institutional email vs. webmail bans, letterhead, stamps, wet/electronic signatures, word/page/file-size limits)?

---

## 1. What Universities and Scholarship Funders Ask Referees to Write

### 1.1 UK Universities (Oxford, Cambridge, LSE, Imperial)

- **University of Oxford:**
  - Applicants must register three referees, though only two submitted references are needed by the deadline for an application to be considered ready for assessment.[^1]
  - Oxford instructs referees to state their own background and qualifications and explain the capacity in which they know the applicant so selectors can judge the basis of the assessment.[^2][^3]
  - Referees must evaluate the applicant's general suitability for the proposed course and how well the course aligns with their experience and interests.[^4]
  - For applicants on an in-progress degree, referees should report interim grades and confirm any prizes awarded and extra-curricular activities undertaken.[^5][^6]
  - Oxford specifically asks for evidence of five core skill areas where relevant: critical thinking, independent and collaborative work, written and oral communication skills, ability to organise workload, and data analysis.[^7]
  - Oxford explicitly instructs referees **not** to include irrelevant material such as protected characteristics (e.g., ethnicity or sexual orientation), personal extenuating circumstances without the applicant's explicit agreement, or the names/details of other students.[^8][^9][^10]

- **University of Cambridge:**
  - Cambridge divides its online reference portal into three parts:
    - **Part 1 (Referee Background):** Name, role, and institution when the referee knew the applicant directly, and the duration of acquaintance.[^11]
    - **Part 2 (Categorical & Comparative Rankings):** Three structured questions covering: (1) the student's academic performance relative to others, including the size of the comparison group;[^12] (2) potential for originality, creativity, and independence of thought based on work taught;[^13] and (3) suitability for the specific course and qualification level (e.g., MPhil or PhD) given existing experience.[^14]
    - **Part 3 (Uploaded Reference Letter — 7 Recommended Headings):**
      1. Expected final result and any interim grades for incomplete degrees, explaining any discrepancy between the two.[^15]
      2. Academic potential on the proposed course, including the relevance of courses taken to date and the logic of the new course for academic development.[^16]
      3. Intellectual characteristics: intellectual curiosity, critical thinking, analytical reasoning, coherent argument, and relevant technical competence.[^17]
      4. Motivation: persistence when facing challenges and drive to complete set tasks, including the proposed course.[^18]
      5. Task and time management, particularly when working independently.[^19]
      6. Effectiveness as a student: responsiveness to feedback, capacity for self-reflection and development, and ability to work and communicate within an intellectual community.[^20]
      7. Summary view: whether the referee would want to supervise the student themselves or offer them a place within their own research group.[^21]

- **London School of Economics and Political Science (LSE):**
  - If an applicant applies for two LSE programmes, a single reference must cover both programmes (LSE does not request a second reference).[^22]
  - LSE asks for four specific elements:
    1. Detailed commentary on university progress and all marks to date if the applicant is a current student at an institution that does not issue transcripts until graduation.[^23]
    2. A candid assessment speaking with maximum specificity to academic suitability for the target programme(s), intellectual strengths, and any limitations.[^24]
    3. For applicants in quantitative subjects, a synopsis of course contents or elaboration on quantitative skills to supplement transcript module titles.[^25]
    4. A direct answer to the benchmark question: *"Would you offer this student a place on a similar programme at your own institution?"*[^26]

- **Imperial College London:**
  - Imperial places particular value on the assessment of previous academic performance and indications of the strength of the applicant's motivation to study the chosen subject.[^27]

### 1.2 Continental European Universities (ETH Zurich, TUM, KU Leuven, Leiden, TU Delft)

- **ETH Zurich:**
  - Referees contacted via ETH's eApply/eReference system provide a short estimation of the applicant's academic performance and upload a letter of recommendation.[^28]
  - Where Master's programmes publish specific content expectations (e.g., MSc Nuclear Engineering), ETH asks for two academic letters describing bachelor-level academic performance and attitude, comments on current GPA, a peer-group ranking of the student, and communication skills.[^29]
  - For applicants also applying to the ETH Excellence Scholarship & Opportunity Programme (ESOP), the two recommendation letters submitted for the Master's application are automatically used for both admissions and the ESOP scholarship.[^30]

- **Technical University of Munich (TUM):**
  - Where TUM programmes require recommendation letters (such as the M.Sc. in Computational Science and Engineering), TUM provides an official structured PDF form combined with a recommendation letter.[^31]
  - The form asks for personal impressions of intellectual ability, aptitude in research or professional skills, ability to carry out advanced studies and research, character, and capacity to adapt to foreign cultures.[^32]
  - It mandates three structured items:
    1. Duration and extent of acquaintance with the applicant.[^33]
    2. Cohort percentile ranking among comparable students across six tiers: *Exceptional (top 3%)*, *Outstanding (top 10%)*, *Very Good (top 20%)*, *Good (top third)*, *Above average (top 50%)*, or *Below average (bottom 50%)*.[^34]
    3. A binary attestation of whether the applicant is among the top 20% of their class (*Yes / No*).[^35]

- **KU Leuven:**
  - For the Science@Leuven Scholarship, applicants must provide two reference letters from internationally renowned professors.[^36]
  - For KU Leuven's Global Minds / Lovanium Doctoral Scholarships, applicants must submit two recommendation letters on KU Leuven's official form from external, relevant referees (explicitly excluding the PhD supervisor or local co-supervisor).[^37]

- **Leiden University:**
  - Selective Master's programmes requiring recommendations (e.g., MSc International Relations and Diplomacy) ask referees to describe the applicant's skills, qualities, and competencies.[^38]

- **TU Delft:**
  - TU Delft requires a reference letter only for MSc applicants applying for a TU Delft scholarship (one letter in English or Dutch).[^39][^40]

### 1.3 Major Scholarship Funders

- **DAAD (German Academic Exchange Service):**
  - DAAD's portal-generated recommendation form and programme instructions (such as RISE Germany) require referees to answer five structured questions:
    1. Since when and in what capacity the referee has known the applicant.[^41]
    2. Quantitative student ranking across five buckets: among the best *5%*, *10%*, *20%*, *30%*, or *no assessment possible*.[^42]
    3. How the applicant stands out in academic and personal terms and an assessment of their potential.[^43]
    4. The significance of the aspired scholarship to the applicant's academic and professional career.[^44]
    5. Overall degree of approval: *Emphatic approval*, *Approval*, or *Conditional Approval*.[^45]

- **Chevening Scholarships:**
  - Referees must state their contact details (address, email, phone number), how long they have known the applicant, in what capacity, and when they last had regular contact.[^46]
  - The letter must provide a brief endorsement covering three pillars: (1) leadership and networking skills, (2) personal and interpersonal qualities, and (3) ability to complete a demanding academic programme in the UK.[^47]

- **Fulbright U.S. Student Program (Study/Research):**
  - Fulbright instructs recommenders to evaluate the candidate both for academic excellence and as a cultural ambassador representing the United States.[^48]
  - Recommenders are asked to comment specifically on:
    1. Feasibility of the proposed project given host-country resources and research environment.[^49]
    2. Appropriateness of the project and subject matter for the host country.[^50]
    3. Suitability of the proposed research methodology given the topic and applicant's background.[^51]
    4. Ability to carry out the research project and/or degree program within the allotted grant period.[^52]
    5. Linguistic preparation for the proposed plan.[^53]
    6. Ability to adapt to a different cultural environment and represent the U.S. as a cultural ambassador.[^54]

- **Gates Cambridge Scholarship:**
  - In addition to the two academic references for Cambridge admission, Gates Cambridge requires a separate third reference assessing how the applicant meets the scholarship's specific criteria.[^55]
  - The portal asks the Gates Cambridge referee to address four criteria: (1) intellectual ability, (2) justification for the choice of course, (3) commitment to improving the lives of others, and (4) leadership capacity.[^56]
  - The referee must also answer: *"How highly would you rank the applicant for a Gates Cambridge Scholarship? On what overall group are you basing this ranking? What is the size of this group?"*[^57] and select a categorical rating from four tiers: *exceptional*, *strong*, *not strong*, or *weak*.[^58]
  - Gates Cambridge explicitly warns that if an academic referee also writes the Gates reference, they must know the applicant's personal qualities and write specifically about the Gates criteria rather than submitting a generic third academic reference.[^59]

- **Rhodes Scholarship:**
  - **Academic referees** (whose references may also be re-used by Oxford departments and colleges for admission if the candidate succeeds)[^60] must answer three cohort-standing questions:
    - Relative academic standing compared to peers on the same course at the same institution (e.g., *top 1%, 3%, 5%, 10%, 25%*).[^61]
    - Total number of students in the comparison year group.[^61]
    - Whether the ranking is based on personal assessment or official class rank.[^61]
  - **Character (non-academic) referees** must focus on character and personal qualities demonstrating promise of outstanding leadership and achievement in later life, addressing: (1) energy to use their talents to the full, (2) virtues and how the candidate lives out their values in daily life, and (3) moral force of character and instincts to lead.[^62]

- **Erasmus Mundus Joint Masters (Mundus Journalism):**
  - Requires two references—one academic and one professional—evaluating the applicant's academic work and workplace performance respectively.[^63]

- **Stipendium Hungaricum:**
  - Standard Bachelor's, Master's, and One-Tier Master's calls do not list a general recommendation letter in the central compulsory document checklist (requiring instead a motivation letter, language proof, certificates, transcripts, ID, and medical certificate where applicable), whereas doctoral (PhD) applicants must submit a signed Letter of Recommendation from a former or current academic tutor or supervisor who holds a scientific degree and has insight into the applicant's professional work.[^64]

- **Global Korea Scholarship (GKS):**
  - Requires one recommendation letter completed on the official form downloaded from the GKS application system.[^65][^66]

---

## 2. Academic vs. Professional Referee Expectations & Eligibility Rules

| Institution / Funder | When Professional Referees Are Permitted or Required | Specific Evaluation Shifts for Professional Referees |
| :--- | :--- | :--- |
| **University of Cambridge** | Out of higher education **$\le 3$ years**: 2 academic referees required.[^67] Out **4–6 years**: 2 academic if possible, else 1 academic + 1 professional.[^68] Out **$> 6$ years**: 2 academic if possible, else 1 academic + 1 professional, or 2 professional if no academic referee is available.[^69] PhD students must **not** be nominated directly as referees.[^70] | Replaces peer class-rank with *"intellectual ability demonstrated in their professional role"*;[^71] evaluates *"professional effectiveness"* in a workplace context;[^72] and replaces the supervision question with *"whether you would want to appoint the applicant to a project team that you were leading."*[^73] |
| **University of Oxford** | Academic referees are preferred, with professional referees permitted depending on time out of study or course guidance; family, friends, or neighbours are never acceptable.[^74] | Acknowledge that professional referees may not observe all academic skills, asking them instead to *"identify specific examples where the applicant has demonstrated the qualities and experience relevant to their intended course."*[^75] |
| **Imperial College London** | 1 must be an academic reference; the 2nd may be academic or, where appropriate/relevant, a professional referee.[^76] | Used to establish *"postgraduate career development"* and required for courses stipulating relevant work experience for entry.[^77] |
| **Leiden University** | Requires 2 letters; at least 1 must be from the applicant's previous university.[^78] | Evaluates workplace skills, qualities, and competencies.[^38] |
| **TU Delft** | 1 letter (for scholarship applicants) from a previous professor/assistant professor, or from an employer if the applicant has work experience.[^40] | Same formal attestation (signed, applicant's full name, preferably on company letterhead with company stamp).[^40] |
| **DAAD** | **Academic tracks (e.g., RISE Germany, Study Scholarships):** Referee must hold at least a PhD; company letters are **not** accepted.[^79][^80] **Development-Related Postgraduate Courses (EPOS):** Requires an employer recommendation from the current employer.[^81] | EPOS employer reference verifies professional employment context and career relevance for development-related study.[^81] |
| **Chevening** | Applicants provide 2 referees: two professional, two academic, or one of each (friends or relatives forbidden).[^82][^83] | Must endorse leadership, networking, interpersonal qualities, and ability to complete a demanding UK Master's programme.[^47] |
| **Gates Cambridge** | The 3rd (scholarship-specific) referee can be an academic advisor aware of personal attributes, a current/former employer, or a senior member of a volunteer organisation.[^84] | Evaluates commitment to improving the lives of others and leadership capacity alongside intellectual ability and course justification.[^56] |
| **Erasmus Mundus (Mundus Journalism)** | Strictly requires **1 academic** reference (professor, department head, dean, or faculty advisor) and **1 professional** reference (current or former employer).[^63] | Balances academic preparedness with journalism/media workplace experience.[^63] |

---

## 3. Authorship, Confidentiality, Portal Attestations & Formatting Formalities

### 3.1 Confidentiality, Portal Submission vs. Applicant Upload, and Anti-Editing / AI Rules

- **Strict Confidential Referee-Only Portal Submission (Applicant Upload Forbidden):**
  - **Oxford:** References uploaded by the applicant themselves are **not permitted** and will not be considered authentic.[^74] Under UK GDPR, Oxford gives referees an opt-in checkbox on the portal form (or a header note on emailed/hard-copy letters) to mark the reference confidential; otherwise, it may be disclosed under a Subject Access Request.[^85]
  - **Cambridge:** Submitted via the referee portal; Cambridge treats all references as supplied in confidence and exempt from UK GDPR right-of-access disclosure to the student.[^86] Cambridge explicitly checks the identity and legitimacy of all referees, imposes a 5-year application ban for false or misleading applications,[^87][^88] and prohibits the use of AI when writing personal statements and CVs (including for English-language enhancement).[^89]
  - **ETH Zurich:** Submitted strictly via ETH's eReference system; letters are confidential and applicants have no access to the documents.[^28] Referees can view their uploaded letter via their link for 7 days after submission before the URL expires.[^90]
  - **Rhodes Scholarship:** Strictly confidential; applicants cannot view the contents of references.[^91] Rhodes explicitly prohibits third-party editing or curating of reference letters prior to portal upload, even where universities review letters for internal endorsement.[^92]
  - **Fulbright U.S. Student Program:** Submitted confidentially through the online system; recommenders are instructed not to share their submission with the applicant.[^93]
  - **DAAD (Study Scholarships / Portal Form):** Generated in the DAAD portal as a writable PDF sent to the referee; DAAD states that *"The document is confidential and may not be viewed by the applicant!"*[^94][^95] (By contrast, for DAAD EPOS employer references, the letter is submitted *"not in a sealed envelope"* as part of the application set.[^81])

- **Applicant-Uploaded or Dual-Channel Workflows:**
  - **TUM (M.Sc. CSE):** The applicant fills in and signs the top of the recommendation form, gives it to the professor, receives the completed form and letter back, and uploads a scan in TUMOnline.[^31]
  - **Chevening:** Chevening does not contact referees during application submission; the referee returns the completed letter to the applicant, who uploads it directly to Chevening's online portal (subject to later verification by the British embassy or high commission).[^96][^97]
  - **Global Korea Scholarship (GKS):** The recommender completes and signs the downloaded GKS form, and the applicant uploads a scanned copy in Round 1 and submits the physical original letter in Round 2.[^66][^98][^99]
  - **Leiden University:** Offers two explicit options: Option 1 (applicant uploads the signed letterhead document in `uSis`) or Option 2 (referee sends it directly to the university).[^100][^101]
  - **KU Leuven (Science@Leuven) & Erasmus Mundus (Mundus Journalism):** Prefer letters uploaded by the applicant in the application package, while offering a direct coordinator email address (`band@au.dk` at Mundus Journalism; Miss Bieke Dutoit at Science@Leuven) if the referee prefers strict confidentiality.[^36][^102]

### 3.2 Institutional Email Requirements vs. Webmail Bans

- **Strict Ban on Personal/Webmail Accounts:**
  - **ETH Zurich:** Accepts official email addresses only; letters from private email accounts (e.g., `@hotmail` or `@gmail`) are **not** accepted.[^103]
  - **Imperial College London:** Requires the referee's professional email account and **cannot** accept references from personal accounts.[^76]
- **Institutional Email Required with Documented Exception Path:**
  - **Oxford:** Referees must be registered with an institutional or professional email address where possible; if impossible, the reference letter must explain why, and an institutional email address must still be entered where prompted in the application form.[^74]
  - **Cambridge:** Expects an academic email address (usually containing `.ac` or `.edu`). If unavailable, the referee must use institutional headed paper on every page, provide full contact details, and include a brief explanation of their position and why an alternative email is used.[^104]
  - **LSE:** Requires official institutional/company email addresses (e.g., `.edu`, `.ac.uk`, `.org`) rather than webmail (`Gmail`, `Hotmail`, `163`).[^105] If an offer holder's reference was submitted from webmail, LSE may require a resupply from an official institutional email or by post on official letterhead/security paper.[^106]

### 3.3 Letterhead, Signatures, Stamps, and Length/File-Size Limits

| Institution / Funder | Letterhead & Stamp Rule | Signature Rule | Length & File Format / Size Limit |
| :--- | :--- | :--- | :--- |
| **Oxford** | Institutional headed paper expected if non-institutional email is used | Signed by referee | **500–1,000 words**, max **2 pages**;[^107] `.pdf`, `.jpeg`, or `.png` (Word documents rejected).[^108] |
| **Cambridge** | Headed paper on **every page** if not using `.ac`/`.edu` email[^104] | **Signed and dated**[^109] | **500–1,000 words**;[^110] `.pdf` only, max **2 MB**.[^109] |
| **ETH Zurich** | Institutional letter uploaded via eReference | Signed letter | `.pdf` only (`.doc`, `.xls`, `.jpg`, `.txt` rejected), max **5 MB**.[^111][^112] |
| **Leiden University** | **Mandatory** letterhead paper with full referee contact details[^113] | **Mandatory** signature[^113] | Standard portal upload (`uSis`) or direct referee dispatch.[^100][^101] |
| **TU Delft** | Official letterhead and university/company **stamp** preferred (not mandatory)[^40] | **Mandatory** signature + applicant's full name[^40] | 1 letter in English or Dutch.[^40] |
| **DAAD** | **RISE:** Official university letterhead mandatory.[^79] **EPOS:** Official letterhead + **official stamp** + current date mandatory.[^81] | **Mandatory** signature[^79][^81] | Portal writable PDF form or letterhead upload.[^94] |
| **Chevening** | Written in English, addressed to the British embassy/high commission in the applicant's country[^114] | Referee contact details required[^46] | Uploaded by applicant as PDF in online system.[^97] |
| **Fulbright (US)** | Institutional/organization letterhead requested (or name and mailing address at top of page 1 if unavailable)[^115] | **Wet or electronic signatures** are both explicitly acceptable[^115] | Submitted via Fulbright online recommendation portal.[^115] |
| **Gates Cambridge** | Online portal text box or separate uploaded letter[^58] | Submitted via authenticated referee portal | Up to **4,000 characters** pasted/typed online, or separate uploaded letter.[^58] |
| **Rhodes Scholarship** | Official/institutional letterhead required (or personal letterhead stating institutional affiliation and official contact details)[^116] | **Mandatory** signature[^116] | Max **2 A4 or letter pages** (minimum **10-point font**); pages beyond page 2 are disregarded.[^117] `.pdf` format.[^116] |
| **Erasmus Mundus (Mundus Journalism)** | **Mandatory** official letterhead[^118] | **Mandatory** signature (*"Unsigned letters of reference will not be considered"*)[^118] | Included in application PDF package or emailed to coordinator.[^102] |
| **Stipendium Hungaricum (PhD)** | Written in the language of the study programme or Hungarian by a supervisor with a scientific degree[^64] | **Mandatory** signed letter[^64] | Max **4 MB** per file in the DreamApply portal.[^119] |
| **GKS (Global Korea Scholarship)** | Official downloaded GKS recommendation form[^66] | **Mandatory** signature; scanned copy in Round 1, **physical original** required in Round 2[^98][^99] | 1 recommendation letter.[^65] |

---

## Sources

[^1]: https://www.ox.ac.uk/admissions/graduate/application-guide/references/registering-referees "You must register three referees as part of your graduate application. However, you need only two references submitted in time for the application deadline to be considered ready for assessment, as long as your application is otherwise complete."
[^2]: https://www.ox.ac.uk/admissions/graduate/application-guide/references/information-for-referees "Briefly state your own background and qualifications so we understand the basis of your assessment"
[^3]: https://www.ox.ac.uk/admissions/graduate/application-guide/references/information-for-referees "Explain the capacity in which you know the applicant, so our assessors can appreciate how well positioned you are to comment on their suitability."
[^4]: https://www.ox.ac.uk/admissions/graduate/application-guide/references/information-for-referees "You should cover the applicant's general suitability to undertake the proposed course and how well the course matches their experience and interests"
[^5]: https://www.ox.ac.uk/admissions/graduate/application-guide/references/information-for-referees "Interim grades from any in-progress course"
[^6]: https://www.ox.ac.uk/admissions/graduate/application-guide/references/information-for-referees "Confirm any prizes awarded and extra-curricular activities undertaken"
[^7]: https://www.ox.ac.uk/admissions/graduate/application-guide/references/information-for-referees "It would also be helpful to include evidence of the following examples of skills where possible/relevant: Critical thinking Independent and collaborative work Written and oral communication skills Ability to organise workload Data analysis"
[^8]: https://www.ox.ac.uk/admissions/graduate/application-guide/references/information-for-referees "Material that is irrelevant to the application, such as protected characteristics like ethnicity or sexual orientation"
[^9]: https://www.ox.ac.uk/admissions/graduate/application-guide/references/information-for-referees "Personal extenuating circumstances without the applicant’s explicit agreement"
[^10]: https://www.ox.ac.uk/admissions/graduate/application-guide/references/information-for-referees "The names or details of students or individuals other than the applicant themselves"
[^11]: https://www.postgraduate.study.cam.ac.uk/apply/how/academic-referees "You are asked to give your name, your role and institution when you knew the applicant directly, and how long that was for. This helps us interpret your comments."
[^12]: https://www.postgraduate.study.cam.ac.uk/apply/how/academic-referees "The student’s academic performance relative to others. You're also asked about the size of the group against which you are comparing the student."
[^13]: https://www.postgraduate.study.cam.ac.uk/apply/how/academic-referees "The student’s potential for originality, creativity and independence of thought, based on their work when you taught them."
[^14]: https://www.postgraduate.study.cam.ac.uk/apply/how/academic-referees "The student’s suitability for the course and its level of qualification (eg MPhil or PhD), given their existing experience."
[^15]: https://www.postgraduate.study.cam.ac.uk/apply/how/academic-referees "For a student who is yet to complete their degree, their expected final result and any interim grades. Please explain any discrepancy between the two."
[^16]: https://www.postgraduate.study.cam.ac.uk/apply/how/academic-referees "For all students, their academic potential on the proposed course, including the relevance of courses taken to date and the logic of the new course for their academic development."
[^17]: https://www.postgraduate.study.cam.ac.uk/apply/how/academic-referees "Their intellectual characteristics: their intellectual curiosity and their abilities in critical thinking, analytical reasoning and coherent argument, as well as any relevant technical competence."
[^18]: https://www.postgraduate.study.cam.ac.uk/apply/how/academic-referees "Their motivation: their persistence when faced with challenges and their drive to complete set tasks, including their proposed course."
[^19]: https://www.postgraduate.study.cam.ac.uk/apply/how/academic-referees "Their task and time management, in particular when they are working independently."
[^20]: https://www.postgraduate.study.cam.ac.uk/apply/how/academic-referees "Their effectiveness as a student: their responsiveness to feedback, their capacity for self-reflection and development, and their ability to work and communicate with others in an intellectual community."
[^21]: https://www.postgraduate.study.cam.ac.uk/apply/how/academic-referees "Your summary view: whether you would want to supervise the student yourself or offer them a place within your own research group."
[^22]: https://www.lse.ac.uk/study-at-lse/Graduate/Prospective-students/Supporting-documents/Information-for-Referees "If the student is applying for two LSE programmes, please ensure that your single reference applies to both programmes (we will not ask you for a second reference)."
[^23]: https://www.lse.ac.uk/study-at-lse/Graduate/Prospective-students/Supporting-documents/Information-for-Referees "If you are an academic referee from an institution which does not supply transcripts or mark sheets until graduation, and if the applicant is a current student, please, if possible, comment in detail on the applicant's progress at university, including all of their marks to date."
[^24]: https://www.lse.ac.uk/study-at-lse/Graduate/Prospective-students/Supporting-documents/Information-for-Referees "We would be grateful for a candid reference that speaks with as much specificity as possible to the candidate’s academic suitability for the programme(s) applied to, their intellectual strengths, and any limitations."
[^25]: https://www.lse.ac.uk/study-at-lse/Graduate/Prospective-students/Supporting-documents/Information-for-Referees "If the applicant’s degree is in a quantitative subject, it is extremely helpful to our selectors if you are able to give some additional information on the modules included in the transcript, for example by including a synopsis of the course contents or by elaborating on their quantitative skills."
[^26]: https://www.lse.ac.uk/study-at-lse/Graduate/Prospective-students/Supporting-documents/Information-for-Referees "Finally, it would be great if you could give an answer to the question, \"Would you offer this student a place on a similar programme at your own institution?\""
[^27]: https://www.imperial.ac.uk/study/apply/postgraduate-taught/application-process/reference/ "The assessment of previous academic performance is of particular value, as are indications of the strength of an applicant's motivation to study the chosen subject."
[^28]: https://ethz.ch/applications/teaching/en/applications/eapply/msc/ref_persons.html "After you have submitted your application, the persons you entered will be contacted by email and asked to give a short estimation of your academic performance and upload a letter of recommendation. The letters of recommendation submitted are confidential and can only be viewed by the responsible staff processing the application. The applicants themselves do not have access to the documents."
[^29]: https://ethz.ch/en/studies/master/application/master-nucleareng.html "Two academic recommendation letters describing : academic performances and attitude at Bachelor level comments on current GPA ranking of the students, comparing with peer group communication skills"
[^30]: https://ethz.ch/applications/teaching/en/applications/eapply/msc/ref_persons.html "If you have already organised two letters of recommendation for your Master’s degree application, no further steps are required for the scholarship application. The letters of recommendation will be used for both the Master’s degree application and the ESOP application."
[^31]: https://www.cit.tum.de/fileadmin/w00byx/cit/Studium/Studiengaenge/Master_Computational_Science_and_Engineering/recommendation_letter.pdf "Please fill in your name, sign the form, and give this form to a professor or other person who is well acquainted with your academic work. Ask your recommender to mail the completed form along with his/her recommendation letter back to you. You should then upload a scan of this document as part of your application documents in TUMOnline."
[^32]: https://www.cit.tum.de/fileadmin/w00byx/cit/Studium/Studiengaenge/Master_Computational_Science_and_Engineering/recommendation_letter.pdf "We would appreciate your personal impressions of the applicant’s intellectual ability, aptitude in research or professional skills as well as his/her ability to carry out advanced studies and research. Comments on the applicant’s character and his/her capacity to adapt to foreign cultures are welcome too."
[^33]: https://www.cit.tum.de/fileadmin/w00byx/cit/Studium/Studiengaenge/Master_Computational_Science_and_Engineering/recommendation_letter.pdf "1. How long and to what extent have you known the applicant?"
[^34]: https://www.cit.tum.de/fileadmin/w00byx/cit/Studium/Studiengaenge/Master_Computational_Science_and_Engineering/recommendation_letter.pdf "2. Among approx. students you have known in comparable fields, how would you rank the applicant? Exceptional (top 3%) Outstanding (top 10%) Very Good (top 20%) Good (top third) Above average (top 50%) Below average (bottom 50%)"
[^35]: https://www.cit.tum.de/fileadmin/w00byx/cit/Studium/Studiengaenge/Master_Computational_Science_and_Engineering/recommendation_letter.pdf "3. The applicant is among the top 20% of his/her class. Yes No."
[^36]: https://wet.kuleuven.be/english/scienceatleuvenscholarship/application "two reference letters of internationally renowned professors. Preferably, these letters are uploaded in the admissions application tool. If referees want to send them directly, they can email them to Miss Bieke Dutoit . Name of the candidate and Science@Leuven Scholarship should be mentioned in the subject line;"
[^37]: https://www.kuleuven.be/global/global-development/research-possibilities/phdcalls/application "Two letters of recommendation from external, relevant referees (i.e. not by your supervisor or local co-supervisor). Please use this form only."
[^38]: https://www.universiteitleiden.nl/en/education/study-programmes/master/international-relations-and-diplomacy/admission-and-application/required-documents "Your referee should describe your skills, qualities and competencies."
[^39]: https://www.tudelft.nl/en/education/admission-and-application/msc-international-diploma/required-documents "Only required for applicants applying for a scholarship listed on our website."
[^40]: https://www.tudelft.nl/en/education/admission-and-application/msc-international-diploma/required-documents "One reference letter in either English or Dutch. The letter must meet the following criteria: Reference provider: The letter should be from: a previous professor or assistant professor. from your employer, if you have work experience. Format: While not mandatory, the letter should preferably be: written on official letterhead. Include the official stamp of the university or company. Content: the letter must be: signed by the referee include your full name."
[^41]: https://www.daad.de/rise/en/rise-germany/find-an-internship/what-applicants-need-to-know/ "Since when and in what capacity have you known the applicant?"
[^42]: https://www.daad.de/rise/en/rise-germany/find-an-internship/what-applicants-need-to-know/ "The applicant is among the best students (in %): 5 %; 10 %; 20%; 30%; or no assessment possible"
[^43]: https://www.daad.de/rise/en/rise-germany/find-an-internship/what-applicants-need-to-know/ "no assessment possible How does the applicant stand out in academic and personal terms and how would you assess his/her potential?"
[^44]: https://www.daad.de/rise/en/rise-germany/find-an-internship/what-applicants-need-to-know/ "Of what significance is the aspired scholarship to the applicant’s academic and professional career?"
[^45]: https://www.daad.de/rise/en/rise-germany/find-an-internship/what-applicants-need-to-know/ "Degree of approval: Emphatic approval; Approval; Conditional Approval"
[^46]: https://www.chevening.org/guidance/references/ "Include your contact details (address, email, phone number), the length of time you’ve known the applicant, the capacity in which you know them, and when you last had regular contact."
[^47]: https://www.chevening.org/guidance/references/ "The letter should provide a brief endorsement of the applicant, covering their leadership and networking skills, personal, and interpersonal qualities, and their ability to complete a demanding academic programme in the UK."
[^48]: https://us.fulbrightonline.org/instructions-for-study-research-recommendation-writers "In completing the recommendation, keep in mind that the applicant will be serving as a cultural ambassador representing the United States and that personal attributes, as well as academic excellence, are important criterion to be considered."
[^49]: https://us.fulbrightonline.org/instructions-for-study-research-recommendation-writers "Feasibility of the applicant's proposed project in terms of the resources available and the research environment within the host country"
[^50]: https://us.fulbrightonline.org/instructions-for-study-research-recommendation-writers "Appropriateness of the project and subject matter for the host country"
[^51]: https://us.fulbrightonline.org/instructions-for-study-research-recommendation-writers "Suitability of the proposed research methodology given the topic and the applicant’s background"
[^52]: https://us.fulbrightonline.org/instructions-for-study-research-recommendation-writers "Ability of the applicant to successfully carry out the proposed research project and/or degree program within the allotted grant period"
[^53]: https://us.fulbrightonline.org/instructions-for-study-research-recommendation-writers "Linguistic preparation for the proposed plan"
[^54]: https://us.fulbrightonline.org/instructions-for-study-research-recommendation-writers "Applicant's ability to adapt to a different cultural environment and to represent the U.S. as a cultural ambassador"
[^55]: https://www.gatescambridge.org/apply/how-to-apply/ "In addition to two academic references for admission, Gates Cambridge applicants must arrange for someone to submit a reference setting out how they meet the scholarship’s criteria."
[^56]: https://www.gatescambridge.org/apply/how-to-apply/ "Please give your assessment of the applicant’s suitability for a Gates Cambridge Scholarship. These are awarded on the following criteria: intellectual ability, justification for the choice of course, a commitment to improving the lives of others and leadership capacity."
[^57]: https://www.gatescambridge.org/apply/how-to-apply/ "How highly would you rank the applicant for a Gates Cambridge Scholarship? On what overall group are you basing this ranking? What is the size of this group?"
[^58]: https://www.gatescambridge.org/apply/how-to-apply/ "Referees are also asked how they rate the applicant for the scholarship: exceptional, strong, not strong, weak. They may paste/type up to 4,000 characters into the online reference or upload a separate letter."
[^59]: https://www.gatescambridge.org/apply/how-to-apply/ "by no means an exhaustive list. Some applicants ask one of their two academic referees to write the Gates Cambridge reference: this is fine as long as that person has a good understanding of your personal qualities and writes specifically about how you meet the Gates Cambridge criteria (and does not simply provide a third academic reference)."
[^60]: https://www.rhodeshouse.ox.ac.uk/files/usarefereeguidance/ "If the applicant is successful, your reference may be re-used by Oxford departments and colleges for determining the applicant’s academic case for admission."
[^61]: https://www.rhodeshouse.ox.ac.uk/files/usarefereeguidance/ "a. What is the applicant’s relative academic standing in comparison with other students on the same course at the same institution – e.g. top 1%, 3%, 5%, 10%, 25%? b. How many students are in the applicant’s year group on their programme of study, i.e. with how many students are you comparing the applicant? c. On what basis are you making the assessment - personal assessment/official class rank?"
[^62]: https://www.rhodeshouse.ox.ac.uk/files/usarefereeguidance/ "If you know the applicant through non-academic activities, your reference should focus on character and personal qualities, in the knowledge that the Committee is looking for scholars who show promise of outstanding leadership and achievement in later life."
[^63]: https://mundusjournalism.com/admissions/application-process "We require two letters of reference: one academic reference from a university official acquainted with your work (e.g. former professor, department head, dean, or faculty advisor), and one professional reference from a current or former employer."
[^64]: https://stipendiumhungaricum.hu/wp-content/uploads/2025/10/PhD_Call_for_Applications_2026_27.pdf "a signed Letter of Recommendation from the applicant’s former or current academic tutor or supervisor, who has a scientific degree and has an insight into the professional work of the applicant, the letter of recommendation must be written in the language of the selected study programme or in Hungarian"
[^65]: https://boston.mofa.go.kr/us-boston-en/brd/m_4558/view.do?seq=761392 "Mandatory Documents: Application form/ Personal statement/ Study plan/ One recommendation letter/ Consent forms/ Self-health statement/ Degree certificates and academic transcripts/ Proof of nationality (applicant and parents)/ Employment certificate (if applicable)"
[^66]: https://boston.mofa.go.kr/us-boston-en/brd/m_4558/view.do?seq=761392 "NOT required ○ Recommendation letters must be filled out in a downloaded form from the system, completed and signed by the recommender, and uploaded by the applicant"
[^67]: https://www.postgraduate.study.cam.ac.uk/apply/how/references "If you're currently studying or finished within the last 3 years You'll need 2 academic referees."
[^68]: https://www.postgraduate.study.cam.ac.uk/apply/how/references "If you left higher education 4-6 years ago You'll need 2 academic referees, if possible. If not, 1 academic and 1 professional referee."
[^69]: https://www.postgraduate.study.cam.ac.uk/apply/how/references "If you left higher education more than 6 years ago You'll need 2 academic referees, if possible. If not, 1 academic and 1 professional referee. If no academic referee is available, 2 professional referees are accepted."
[^70]: https://www.postgraduate.study.cam.ac.uk/apply/how/references "Do not nominate PhD students. If you have been taught by a PhD student and they know your work well, you can encourage your referee to talk to them."
[^71]: https://www.postgraduate.study.cam.ac.uk/apply/how/professional-referees "The applicant’s intellectual ability demonstrated in their professional role. You're also asked to briefly describe your professional position at the relevant time."
[^72]: https://www.postgraduate.study.cam.ac.uk/apply/how/professional-referees "The applicant’s professional effectiveness: their responsiveness to feedback, their capacity for self-reflection and development, and their ability to work and communicate with others in a professional context."
[^73]: https://www.postgraduate.study.cam.ac.uk/apply/how/professional-referees "Your summary view: whether you would want to appoint the applicant to a project team that you were leading."
[^74]: https://www.ox.ac.uk/admissions/graduate/application-guide/references/registering-referees "Where possible, referees must be registered with an institutional or professional email address. If this is not possible, reference letters must explain why, and you must provide an email address for the institution where prompted in the Referees section of the application form. References you upload to your application yourself are not permitted and will not be considered authentic. Personal references (ie from family, friends or neighbours) are never acceptable."
[^75]: https://www.ox.ac.uk/admissions/graduate/application-guide/references/information-for-referees "Depending on the nature of your professional role, you may not be able to speak to all of the above skills, but please try to identify specific examples where the applicant has demonstrated the qualities and experience relevant to their intended course."
[^76]: https://www.imperial.ac.uk/study/apply/postgraduate-taught/application-process/reference/ "One must be an academic reference, the second referee may be another academic referee, or where appropriate/relevant, a professional referee. Please ensure you include your referee's professional email account, as we cannot accept references from personal accounts."
[^77]: https://www.imperial.ac.uk/study/apply/postgraduate-taught/application-process/reference/ "A professional reference can also be of use in establishing an applicant’s postgraduate career development and is a requirement for certain courses which stipulate relevant experience as an entry requirement."
[^78]: https://www.universiteitleiden.nl/en/education/study-programmes/master/international-relations-and-diplomacy/admission-and-application/required-documents "This programme requires two letters of recommendation – one must be from your previous university."
[^79]: https://www.daad.de/rise/en/rise-germany/find-an-internship/what-applicants-need-to-know/ "Please ask your referee (must hold a PhD degree at least) to upload the letter of recommendation in the online database. The letter of reference must be submitted with the official letterhead of the respective university and the referee’s signature."
[^80]: https://www.daad.de/rise/en/rise-germany/find-an-internship/what-applicants-need-to-know/ "We do not accept recommendation letters from companies."
[^81]: https://www2.daad.de/deutschland/stipendium/datenbank/en/21148-scholarship-database/?detail=50076777 "Letter of recommendation from your current employer; the letter must include official letterhead, signature and official stamp and must be of current date (not in a sealed envelope)"
[^82]: https://www.chevening.org/guidance/references/ "You must provide the names of two referees in your application. They can be two professional referees, two academic referees, or one of each."
[^83]: https://www.chevening.org/guidance/references/ "A referee should be someone who knows you in a professional or personal capacity, but not a friend or relative."
[^84]: https://www.gatescambridge.org/apply/how-to-apply/ "Many applicants ask a current or former academic advisor who is aware of their personal attributes, a current or former employer or a senior member of an organisation with whom they have volunteered – although this is by no means an exhaustive list."
[^85]: https://www.ox.ac.uk/admissions/graduate/application-guide/references/information-for-referees "If you wish your reference to be treated as confidential, please select this option in the reference form. If you are submitting your reference letter directly by email or in hard copy and wish it to be treated as confidential, please clearly indicate this at the top of the letter. Otherwise, in the event of a subject access request, your reference may be disclosed to the applicant."
[^86]: https://www.postgraduate.study.cam.ac.uk/apply/how/academic-referees "References are supplied to Cambridge in confidence and, as such, are exempt from the right of access provisions of data protection legislation (UK GDPR). References will not be disclosed to the student or to third parties, including other parts of the University of Cambridge."
[^87]: https://www.postgraduate.study.cam.ac.uk/apply/how/admissions-fraud "We also check the identity and legitimacy of all referees."
[^88]: https://www.postgraduate.study.cam.ac.uk/apply/how/admissions-fraud "You will not be able to apply again within 5 years of submitting a false or misleading application."
[^89]: https://www.postgraduate.study.cam.ac.uk/apply/how/ai-postgraduate-applications "AI must not be used when writing personal statements and CVs. This prohibition covers the use of AI to help your use of English."
[^90]: https://ethz.ch/applications/teaching/en/applications/ereference.html "You can use the URL to view your letter of recommendation and details for 7 days after submitting it. The URL will then expire and the information will no longer be visible."
[^91]: https://www.rhodeshouse.ox.ac.uk/files/usarefereeguidance/ "Once you submit your form, both you and the applicant will receive an automated confirmation email. The applicant will not be able to view the contents of your reference."
[^92]: https://www.rhodeshouse.ox.ac.uk/files/usarefereeguidance/ "Rhodes Scholarship reference letters are intended to remain confidential and should not be shared directly with applicants. While institutions may review letters as part of their internal nomination or endorsement processes, it is important to preserve the integrity of the references. Letters should not be edited or curated by others prior to being uploaded to the application portal."
[^93]: https://us.fulbrightonline.org/instructions-for-study-research-recommendation-writers "Recommendations should remain confidential. Please do not share your submission with the applicant."
[^94]: https://www2.daad.de/deutschland/stipendium/datenbank/en/21148-scholarship-database/?detail=50019749 "You can generate the recommendation form in the DAAD portal as a writable PDF under 'Request recommendation form'. Please send it to your referee and ask him or her to complete the form in full."
[^95]: https://www2.daad.de/deutschland/stipendium/datenbank/en/21148-scholarship-database/?detail=50019749 "The document is confidential and may not be viewed by the applicant!"
[^96]: https://www.chevening.org/guidance/references/ "Remember, Chevening won’t contact your referees for you – you must collect and upload the references yourself. However, the British embassy or high commission may later contact them for verification."
[^97]: https://www.chevening.org/guidance/references/ "Once you have completed your reference letter, please return it to the applicant, who will then upload it to Chevening’s online application system or submit it directly to their Chevening team."
[^98]: https://fi.mofa.go.kr/fi-en/brd/m_9572/view.do?seq=761757 "Letter of Recommendation (No.5)Upload a scanned copy of the signed recommendation letter to the system"
[^99]: https://fi.mofa.go.kr/fi-en/brd/m_9572/view.do?seq=761757 "Letter of Recommendation (No.5)The original letter of recommendation must be submitted"
[^100]: https://www.universiteitleiden.nl/en/education/study-programmes/master/international-relations-and-diplomacy/admission-and-application/required-documents "Option 1. Uploading the letter yourself You can upload the letter(s) of recommendation in the online application portal (uSis)."
[^101]: https://www.universiteitleiden.nl/en/education/study-programmes/master/international-relations-and-diplomacy/admission-and-application/required-documents "Option 2. Sent by your referee Your referee can send the letter directly to the university"
[^102]: https://mundusjournalism.com/admissions/application-process "Unsigned letters of reference will not be considered. If possible, we prefer the reference letters to be included in the application package, but if your referees would prefer the reference to be treated in confidence, please refer them to Bettina Andersen at band@au.dk."
[^103]: https://ethz.ch/applications/teaching/en/applications/eapply/msc/ref_persons.html "Please provide official email addresses only. Letters of recommendation from private email accounts (e.g. @hotmail or @gmail) can unfortunately not be accepted."
[^104]: https://www.postgraduate.study.cam.ac.uk/apply/how/academic-referees "To help with verification, we expect applicants to provide an academic email address for their referees (usually containing .ac or .edu). If you do not have an academic email address, please use your institution’s headed paper for each page of the reference letter and provide full contact details. Please include a brief explanation of your position and why an alternative email address is being used."
[^105]: https://www.lse.ac.uk/study-at-lse/Graduate/Prospective-students/Supporting-documents/How-do-I-supply-references "You should enter each referee’s official institutional (academic or professional/company) email address (e.g. ending .edu/.ac.uk/.org) not their webmail address (e.g. Gmail/Hotmail/163)."
[^106]: https://www.lse.ac.uk/study-at-lse/Graduate/Prospective-students/Supporting-documents/How-do-I-supply-references "If your application is successful and if either of your references was originally submitted from a webmail address instead of an official institutional email address, we may require your referee to send us a further copy of their reference either by email using their official institutional email address, or if necessary by post, signed and printed on official letterhead/security paper."
[^107]: https://www.ox.ac.uk/admissions/graduate/application-guide/references/information-for-referees "Reference letters should be typically 500-1,000 words and should not normally exceed two pages. You should write in enough detail to give specific examples of their qualities and achievements, but longer letters will not be taken as indicating greater support."
[^108]: https://www.ox.ac.uk/admissions/graduate/application-guide/references/registering-referees "in PDF, .jpeg or .png format. References cannot be uploaded as Word documents"
[^109]: https://www.postgraduate.study.cam.ac.uk/apply/how/academic-referees "Your reference should be: In English Between 500 and 1,000 words A PDF document No larger than 2MB Signed and dated"
[^110]: https://www.postgraduate.study.cam.ac.uk/apply/how/academic-referees "A reference of 500 to 1,000 words is most effective. Longer references will not give additional help to the student."
[^111]: https://ethz.ch/applications/teaching/en/applications/ereference.html "Only letters of recommendation in PDF format (file extension .pdf) can be uploaded. Other formats such as Word, Excel , .jpg or .txt are not accepted."
[^112]: https://ethz.ch/applications/teaching/en/applications/ereference.html "The file size must not exceed 5 MB."
[^113]: https://www.universiteitleiden.nl/en/education/study-programmes/master/international-relations-and-diplomacy/admission-and-application/required-documents "Letters of recommendation must be written on letterhead paper, signed and (for verification purposes) they must bear the full contact details of the applicable referee."
[^114]: https://www.chevening.org/guidance/references/ "Be addressed to the British embassy/high commission in the applicant’s country or territory."
[^115]: https://us.fulbrightonline.org/instructions-for-study-research-recommendation-writers "We request that letters be submitted on institution/organization letterhead as this is the generally accepted professional standard. If you do not have access to letterhead, please be sure that your name and mailing address are on the top of the first page of the letter. Wet or electronic signatures on the document are both acceptable."
[^116]: https://www.rhodeshouse.ox.ac.uk/files/usarefereeguidance/ "Submit your letter on headed paper, signed, and in PDF format. If you are unable to access an official/institutional letterhead we can accept references on a personal letterhead that clearly states your institutional affiliation and provides official contact information (email address and phone number)."
[^117]: https://www.rhodeshouse.ox.ac.uk/files/usarefereeguidance/ "References must be written in English and your comments should not exceed two A4 or letter size pages (minimum 10-point type). If letters are submitted which are longer than this, only the first two pages will be considered by the Selection Committee in the interests of fairness to all candidates."
[^118]: https://mundusjournalism.com/admissions/application-process "Please ask your referees to submit the reference with an official letterhead, and make sure that it is signed. Unsigned letters of reference will not be considered."
[^119]: https://stipendiumhungaricum.hu/wp-content/uploads/2025/10/PhD_Call_for_Applications_2026_27.pdf "Please note that Only files with a maximum size of 4 MB can be uploaded in to the system."

---

## Open questions

- **Referee-specific generative AI policies:** While Cambridge explicitly bans applicants from using generative AI for personal statements and CVs (including for English-language polishing) and Rhodes prohibits third-party editing or curating of referee letters, none of the 17 inspected primary sources published a standalone policy governing whether an independent *referee* may use generative AI tools to polish their own draft before signing and submitting.
- **Programme-by-programme variance in continental Europe:** At decentralised continental European universities (TUM, KU Leuven, Leiden), whether a reference letter is required at all—and whether it is uploaded by the applicant or submitted confidentially—varies by individual Master's examination regulation rather than a single university-wide graduate rule.
