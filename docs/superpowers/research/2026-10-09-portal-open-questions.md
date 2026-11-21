# Free-text questions on master's application portals, and what they mean for pre-filling

Date: 2026-10-09. Scope: uni-assist, TUMonline, DreamApply, Studyinfo.fi, universityadmissions.se, Studielink, and Erasmus Mundus consortium forms.

## Summary

- **Pick option (ii): a separate harness, not one generic "free text" case.** The portals' open fields fall into five kinds, and each kind gets its answer from a different place: (a) facts the student has already verified, (b) persuasion that has to agree with the approved motivation letter, (c) prompts for knowledge or an essay, which no stored material answers, (d) logistics and preferences, (e) attestations and consents, which only the applicant may give. A generic filler would treat a declaration or an essay prompt like a work-history box.
- **Shared portals pass the open questions through to each university.** uni-assist, Studielink and DreamApply show questions written by each university or programme, so the questions differ by programme. Studyinfo (Turku) and DreamApply (TalTech) put the motivation letter in the form itself, with character limits from 3,000 to 5,500. TUMonline, universityadmissions.se and most Erasmus Mundus consortia take an uploaded PDF instead. Limits are given in characters with spaces, in words, or in pages, and these are not interchangeable.
- **AI rules land hardest on the persuasion type.** TUM forbids AI-created application documents. TalTech and IHE Delft reject or penalise AI text in motivation answers. Aalto requires a declaration of any AI use. So the co-pilot should put the student's own approved text into persuasion fields, not generate new prose there. The attestation type must never be filled.

## Method and sources

- Searches: Exa `web_search_advanced_exa` restricted to each owner's domain (uni-assist.de, tum.de, dreamapply.com, opintopolku.fi/studyinfo.fi, universityadmissions.se, studielink.nl, aalto.fi, utu.fi), plus open Exa searches for Erasmus Mundus consortium guides, AI policies and Dutch university portals. Brave was not needed. Tavily was used only to extract two PDFs.
- Citations come from live scrapling `get` fetches. Two PDFs (the University of Turku Biomedical Sciences question sheet and the i-MESC applicant guide) could not be parsed by scrapling, so they were read with `tavily_extract`. Their quotes come from that extraction and may fail an automated HTML check.
- Not reachable: opintopolku.fi programme pages render only with JavaScript and came back empty. utu.fi/en/study-at-utu/application-form returned HTTP 403. The live portals themselves sit behind logins and were not opened. Everything below comes from the portals' own help pages and from university pages describing them.

## Findings by portal

### uni-assist (Germany)
- **What free text exists:** universities add their own questions behind "Show additional application-related questions"; uni-assist warns that "The universities supply the application forms, so the questions may vary from university to university."[^1] Some of these questions are mandatory, and the fee cannot be paid until they are answered: "Please check that you have answered all the mandatory questions."[^2]
- **Motivation letter:** uploaded, not typed into the form. One upload can serve every application, or there can be one per application: "You can upload an individual letter of motivation or CV for each application."[^3]
- **Limits and question text:** **Unverified.** No public page lists the per-university questions or their limits.

### TUMonline (TUM)
- **Steps:** the current guide lists 11 steps, and prose enters only through uploads at step "8. Document Upload and Language Skills".[^4] No current step is a free-text box. A 2015 TUM PDF described an optional "Further Information" screen; it is not in the current list and is treated here as retired (**Unverified** whether it still exists).
- **Statement of purpose:** uploaded as a PDF. It "should generally be no longer than one page"[^5], "A generic letter of motivation is not sufficient"[^6], and it "must be written by applicants themselves."[^7]
- **Written Statement:** the one place where TUMonline puts questions in front of the applicant. "The Written Statement is based on pre-defined key questions provided during the online application in TUMonline."[^8] It is required only for Business Education I and II, and the answer is still uploaded.
- **AI and plagiarism:** "The use of AI tools such as ChatGPT to create documents for an application at TUM is not permitted."[^9] Also: "All self-created documents are checked for plagiarism by TUM."[^10]
- **Gaps:** TUM handles gaps in the CV, not in a free-text box: "The CV must not contain any gaps longer than 3 months for the period after you left school."[^11]

### DreamApply (TalTech and many others)
- **Motivation section:** a programme can switch it on. It "Adds a section to collect the applicant’s motivation for applying to a programme."[^12] When several programmes are applied for, "DreamApply displays several data entry fields in the Motivation section, prompting an applicant to submit a unique letter for each programme."[^13]
- **Custom fields:** each institution can add its own. "If a suitable question is not available, you can add your own data entry fields."[^14] The questions are therefore open-ended per institution.
- **"How did you hear about us":** a built-in field. "Applicants can choose the channel, or information source, using the Other section on the application edit page."[^15]
- **Consents:** "Mandatory consents must be accepted before applicants can complete registration."[^16]
- **TalTech example:** the letter is typed into the form. "Type in your motivation letter (3000-5500 characters)"[^17]. Also: "AI-generated text is not acceptable as the purpose of the motivation letter is to show the applicant’s genuine motivation."[^18]

### Studyinfo.fi (Finland)
- **University of Turku:** a set of in-form questions makes up the letter. "You cannot edit your answers after the application period has ended (incl. possible motivational questions that form a motivation letter)."[^19] Answers must be in English: "All questions on University of Turku's section on the application form must be answered in English, unless stated otherwise in the question."[^20]
- **Turku Biomedical Sciences question sheet** (read via Tavily):
  - Four motivation sub-questions share one box with a limit of "Maximum 4000 characters including spaces."[^21]
  - One sub-question is about logistics and funding: "Expected living expenses in Finland are minimum 600€/month."[^22]
  - Fact-recall questions follow, for example "Have you published scientific articles?"[^23]
- **Aalto:** the motivation letter is an uploaded document, not an in-form field. "The letter should be maximum 4000 characters (with spaces) and must be written in English."[^24] Each programme needs its own letter: "You should write a separate motivation letter for each study option you apply to."[^25] Applicants "must clearly declare any use of AI tools, if at all, across all parts of the application".[^26]
- **Generic Studyinfo form sections:** **Unverified**, because the pages are JavaScript-only and could not be fetched.

### universityadmissions.se (Sweden)
- **Supplementary letters and essays:** each university decides how they arrive. "It's up to each university to decide how they'd like to receive these special letters/documents they've requested."[^27] One allowed route is an upload: "They may ask you to upload them on this website."[^28]
- **Free-text boxes in the national form:** none found in the help pages (**Unverified**).

### Studielink (Netherlands) and the universities' own portals
- **Studielink:** it only passes institution questions along. "Once you have answered any questions that the educational institution may have and confirmed your selection, your application will be forwarded to the institution."[^29]
- **University portal:** the real application, with motivation material, happens afterwards in the university's own system. Leiden, for example: "In our online application portal (uSis) you can finalise your application by uploading the necessary documents and answering a few questions."[^30] Which questions, and their limits: **Unverified**.

### Erasmus Mundus consortium forms
- **Janus:** "2 questions to answer, one in English and one in French, with a limit of 500 words per question:"[^31] The second question is an essay prompt, not a question about motivation: "2) Describe a current challenge or issue that the European Union is facing in terms of security and defence."[^32]
- **IHE Delft:** the motivation questions are answered in the form. "Please use your own words and avoid the use of AI tools such as Chat GPT when you answer the motivation questions."[^33]
- **MER:** "Motivation Letter: applicant’s personal statement to participate in the programme – (maximum length: 6000 characters)"[^34]. There is also an online "Proposed Study Plan (PSP) Form: teaching modules of preference, research topics of interest and additional information".[^35]
- **i-MESC form specimen** (read via Tavily):
  - Employment field: "Describe, if any, your employment and /or professional experiences (from most recent to oldest)."[^36]
  - Language field: "Explain how you acquired your linguistic skills in this language".[^37]
  - Both the employment and language fields are limited to 500 words.
  - The additional-information field carries a warning: "Please make sure that this information is not redundant with all the other parts of the application form."[^38]
  - Tick-box statements, for example "I confirm the information on this application form is complete and correct."[^39]

## Inventory: open-field types by portal

| Portal | (a) Facts | (b) Programme persuasion | (c) Knowledge or essay | (d) Logistics or marketing | (e) Attestation or consent | Limits seen |
|---|---|---|---|---|---|---|
| uni-assist | university questions (content unverified) | letter is uploaded | none seen | none seen | mandatory questions, "truthfully" | not published |
| TUMonline | CV upload, gaps declared there | SoP uploaded; Written Statement (key questions) | essay uploaded | none seen | none seen in the guide | about 1 page |
| DreamApply | custom extra fields | Motivation section, one per programme | custom fields | Information source field | mandatory consents | TalTech 3,000–5,500 characters |
| Studyinfo (Turku) | publications, thesis, lab months | multi-part motivation box | none seen | funding question, track ranking | **Unverified** | 4,000 characters with spaces; 5,000 characters per Exa snippet, not verified |
| Studyinfo (Aalto) | CV upload | letter uploaded | none seen | none seen | AI-use declaration | 4,000 characters with spaces |
| universityadmissions.se | uploads | upload or direct to the university | upload | none seen | none seen | per university |
| Studielink + uSis/OSIRIS | institution questions (unverified) | in the university portal | none seen | none seen | none seen | **Unverified** |
| Erasmus Mundus | employment, languages (500 words each) | 500 words; 6,000 characters | Janus EU-security essay | study plan, mobility ranking | statements, AI declarations | words or characters |

## Recommended taxonomy, and how each type is answered

1. **FACT**: work experience, language acquisition, publications, thesis title, lab months.
   - Compose from verified facts only.
   - Quality check: every claim traces to a fact in the student's ledger, and nothing is added.
2. **PERSUASION**: why this programme, career plans, why this city, how your background fits.
   - Fill only from the student's approved, programme-specific letter: place or split its sentences, never generate new ones. TUM, TalTech, IHE Delft and Aalto all penalise AI-written persuasion or require it to be declared.
   - Quality checks: no contradiction with the uploaded letter, specific to the named programme, every sub-question covered.
3. **ESSAY**: knowledge prompts such as Janus's EU security question, or TUM essays.
   - The student writes these. The co-pilot shows the prompt and the limit only.
4. **LOGISTICS**: information source, funding plan, track or mobility ranking, scholarship conditionality.
   - Information source can come from the profile.
   - Rankings and funding are the student's choices or facts. Ask the student; never infer them.
5. **ATTESTATION**: declarations, consents, AI-use declarations, "complete and correct" statements.
   - Never filled and never ticked; hand them to the applicant.
6. **OTHER / additional information**: leave empty by default, because i-MESC asks that it not repeat the rest of the form.

The type should be stored per field, alongside the field map's existing `profile_field`. The repo's escalation triggers `PERSONAL_ATTESTATION` and `MISSING_FACT` (CLAUDE.md, not a web source) already match types 5 and 1.

## How to measure quality

- **Router accuracy:** a labelled set of real questions (start with the quoted ones above), scored for type-classification precision and recall. The costly error is calling ESSAY or ATTESTATION a fillable type, so it should be weighted most heavily.
- **Limit compliance:** the limit unit is parsed correctly (characters with or without spaces, words, pages), and the output fits.
- **Faithfulness:** FACT claims are traceable to the ledger, and PERSUASION text overlaps the approved letter with zero contradictions.
- **Programme specificity and sub-question coverage,** for multi-part prompts.
- **Language:** the language each question requires (Janus asks for one answer in French).
- **Correct abstention:** ESSAY, ATTESTATION and unanswered LOGISTICS fields are left empty.

## Open questions

- The actual question wording and limits for uni-assist's university-specific questions, and for Studielink's institution questions plus the Dutch university portals (uSis, OSIRIS, MyApplication). Neither has a public page.
- The generic Studyinfo form sections, and the full text of utu.fi/en/study-at-utu/application-form (403 to automated reads).
- Whether universityadmissions.se has any free-text field in its national form.
- Whether TUMonline still has an optional "Further Information" free-text screen (it was in the 2015 PDF and is absent from the current step list).
- Whether placing a student's own approved letter text into in-form boxes counts as "AI-created" under TUM's or TalTech's rules. That needs a policy reading, not more research.

## Sources

[^1]: https://www.uni-assist.de/en/faqs/apply-online/ "The universities supply the application forms, so the questions may vary from university to university."
[^2]: https://www.uni-assist.de/en/faqs/apply-online/ "Please check that you have answered all the mandatory questions."
[^3]: https://www.uni-assist.de/en/faqs/apply-online/ "You can upload an individual letter of motivation or CV for each application."
[^4]: https://www.tum.de/en/studies/application/application-info-portal/online-application/onlineapplication-bachelor-master "8. Document Upload and Language Skills"
[^5]: https://www.tum.de/en/studies/application/application-info-portal/document-requirements/tum-style-guide "A statement of purpose should generally be no longer than one page."
[^6]: https://www.tum.de/en/studies/application/application-info-portal/document-requirements/tum-style-guide "A generic letter of motivation is not sufficient."
[^7]: https://www.tum.de/en/studies/application/application-info-portal/glossary-of-documents "The statement of purpose must be written by applicants themselves."
[^8]: https://www.tum.de/en/studies/application/application-info-portal/glossary-of-documents "The Written Statement is based on pre-defined key questions provided during the online application in TUMonline."
[^9]: https://www.tum.de/en/studies/application/application-info-portal/document-requirements/tum-style-guide "The use of AI tools such as ChatGPT to create documents for an application at TUM is not permitted."
[^10]: https://www.tum.de/en/studies/application/application-info-portal/document-requirements/tum-style-guide "All self-created documents are checked for plagiarism by TUM."
[^11]: https://www.tum.de/en/studies/application/application-info-portal/document-requirements/tum-style-guide "The CV must not contain any gaps longer than 3 months for the period after you left school."
[^12]: https://help.dreamapply.com/kb/programmes/define-application-form-settings/ "Adds a section to collect the applicant’s motivation for applying to a programme."
[^13]: https://help.dreamapply.com/kb/programmes/define-application-form-settings/ "DreamApply displays several data entry fields in the Motivation section, prompting an applicant to submit a unique letter for each programme."
[^14]: https://help.dreamapply.com/kb/admission-workflow/appforms/create-appforms/ "If a suitable question is not available, you can add your own data entry fields."
[^15]: https://help.dreamapply.com/kb/marketing/use-channels/ "Applicants can choose the channel, or information source, using the Other section on the application edit page."
[^16]: https://help.dreamapply.com/kb/data-protection/collect-consents/ "Mandatory consents must be accepted before applicants can complete registration."
[^17]: https://taltech.ee/en/apply "Type in your motivation letter (3000-5500 characters)"
[^18]: https://taltech.ee/en/apply "AI-generated text is not acceptable as the purpose of the motivation letter is to show the applicant’s genuine motivation."
[^19]: https://www.utu.fi/en/study-at-utu/apply-to-masters-programmes "You cannot edit your answers after the application period has ended (incl. possible motivational questions that form a motivation letter)."
[^20]: https://www.utu.fi/en/study-at-utu/apply-to-masters-programmes "All questions on University of Turku's section on the application form must be answered in English, unless stated otherwise in the question."
[^21]: https://www.utu.fi/sites/default/files/media/Application_form_Biomedical_Sciences.pdf "Maximum 4000 characters including spaces."
[^22]: https://www.utu.fi/sites/default/files/media/Application_form_Biomedical_Sciences.pdf "Expected living expenses in Finland are minimum 600€/month."
[^23]: https://www.utu.fi/sites/default/files/media/Application_form_Biomedical_Sciences.pdf "Have you published scientific articles?"
[^24]: https://www.aalto.fi/en/study-options/chemistry-and-materials-science-master-of-science-technology "The letter should be maximum 4000 characters (with spaces) and must be written in English."
[^25]: https://www.aalto.fi/en/study-options/chemistry-and-materials-science-master-of-science-technology "You should write a separate motivation letter for each study option you apply to."
[^26]: https://www.aalto.fi/en/study-options/chemistry-and-materials-science-master-of-science-technology "all applicants must clearly declare any use of AI tools, if at all, across all parts of the application"
[^27]: https://www.universityadmissions.se/en/support-centre/supporting-documents/ "It's up to each university to decide how they'd like to receive these special letters/documents they've requested."
[^28]: https://www.universityadmissions.se/en/support-centre/supporting-documents/ "They may ask you to upload them on this website."
[^29]: https://info.studielink.nl/en/how-to-use-studielink "Once you have answered any questions that the educational institution may have and confirmed your selection, your application will be forwarded to the institution."
[^30]: https://www.universiteitleiden.nl/en/education/admission-and-application/masters/application-procedure "In our online application portal (uSis) you can finalise your application by uploading the necessary documents and answering a few questions."
[^31]: https://master-janus-security-defense.eu/how-to-apply-janus/ "2 questions to answer, one in English and one in French, with a limit of 500 words per question:"
[^32]: https://master-janus-security-defense.eu/how-to-apply-janus/ "2) Describe a current challenge or issue that the European Union is facing in terms of security and defence."
[^33]: https://apply.un-ihe.org/application-process/master-of-science-erasmus "Please use your own words and avoid the use of AI tools such as Chat GPT when you answer the motivation questions."
[^34]: https://merconsortium.eu/application-enrolment/application/ "Motivation Letter: applicant’s personal statement to participate in the programme – (maximum length: 6000 characters)"
[^35]: https://merconsortium.eu/application-enrolment/application/ "Proposed Study Plan (PSP) Form: teaching modules of preference, research topics of interest and additional information"
[^36]: https://i-mesc.eu/fileadmin/documents/i-MESC_Guide_for_applicants_Accessible_FINAL.pdf "Describe, if any, your employment and /or professional experiences (from most recent to oldest)."
[^37]: https://i-mesc.eu/fileadmin/documents/i-MESC_Guide_for_applicants_Accessible_FINAL.pdf "Explain how you acquired your linguistic skills in this language"
[^38]: https://i-mesc.eu/fileadmin/documents/i-MESC_Guide_for_applicants_Accessible_FINAL.pdf "Please make sure that this information is not redundant with all the other parts of the application form."
[^39]: https://i-mesc.eu/fileadmin/documents/i-MESC_Guide_for_applicants_Accessible_FINAL.pdf "I confirm the information on this application form is complete and correct."
