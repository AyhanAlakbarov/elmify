# Azerbaijani university transcripts, diplomas and diploma supplements: language, script, grading scale

Date: 2026-10-03. For: the transcript reader (OCR, then a row/column classifier) whose launch students come from Azerbaijan.

## Answer first

- **The default is Azerbaijani. English comes only when the graduate asks for it.** ENIC-NARIC's country page for Azerbaijan says the diploma supplement is issued in Azerbaijani, and in English on the graduate's written application.[^2] The newest national rule says the same: the Cabinet of Ministers decision of 7 January 2026 (No. 1), clause 2.5.
  - **Unverified by the checker:** the decision is a PDF the citation checker cannot read. I read it through `tavily_extract`: https://nk.gov.az/uploads/doc/docs/695e626203a59.pdf.
  - The same decisions moved state education documents fully to electronic form, delivered to the graduate's myGov cabinet. Our only checkable source for this is a study-abroad agency blog, not the government.[^36]
- **Bilingual was the 2008 rule; practice and the current rule differ.**
  - **Unverified (PDF):** the 2008 ministerial template (Order No. 990 of 8 August 2008) said the supplement is filled in Azerbaijani plus one widely used European language, "as a rule English", and is issued free at the student's request: https://edu.gov.az/upload/file/diploma-elave-numunesi.pdf. Only the order's number and date are confirmed on an HTML page.[^37]
  - **Unverified (PDF):** a 2018 EU Twinning mission found institutions issued the supplement only on request: https://www.twinning4he.edu.az/uploads/activity-document/mission_report_act41_17_21_dec_2018_signed.pdf.
  - ENIC-NARIC says the supplement is issued automatically.[^38]
  - The current rule is Azerbaijani with English on request: the 2026 decision outranks the 2008 order, and ENIC-NARIC agrees with it.
- **Each university decides whether to offer English.** Of the 15 universities asked about, only UNEC has a primary source for English on request. Since 2022/23 its "Bir Pəncərə" (one-window) service issues documents, including the academic transcript, in Azerbaijani or English as a signed, QR-coded PDF.[^6] ADA, BHOS, Khazar and UFAZ teach mainly or entirely in English.[^7][^8][^9][^10] None of their pages states what language their transcript is in. For the other ten we found nothing. They appear in the table as **Unverified**.
- **Expect an Azerbaijani original plus a notarised translation, not a university-issued English transcript.**
  - uni-assist only accepts translations from Azerbaijan attested by an Azerbaijani notary.[^11]
  - WES does not accept an institution's English version in place of a translation.[^12]
  - Other evaluators (ERES, Educational Perspectives, AES) list Azerbaijani or Russian as document languages, and AES notes that recent documents may also be in English. **Unverified:** their pages refused the checker (HTTP 403) or are PDFs.
- **The reader must handle three scripts at launch:** Azerbaijani Latin (ə ğ ı ö ü ç ş q x), Russian Cyrillic, and, for older documents, Azerbaijani Cyrillic (ә ҝ ҹ ғ ө ү һ ј). It must also handle at least four grading scales: the national 100-point/A–F scale, Khazar's own A–F cut-offs, ADA's 4-point GPA, the French 0–20 scale on UFAZ's Strasbourg documents, and, for older documents, the Soviet-era 5-point word grades.

## Scope and method

Sub-questions:
1. What does the law say about the language of the state diploma and supplement, and is a bilingual supplement mandatory?
2. What does each of the main universities issue, and is English available on request?
3. Do Russian-sector graduates get Russian-language documents?
4. What language and script are pre-2005 and Soviet-era documents in?
5. What do foreign evaluators and receiving universities require?
6. Which grading scales appear, and how are they labelled?

Tools used: Exa (including domain-restricted searches on each university's domain), Brave for exact phrases, scrapling `get` for every cited HTML page, and `tavily_extract` for PDFs.

**What the citation checker could not read, and how the report handles it:**
- **PDFs.** scrapling returned binary for PDFs, and the citation checker could not find text in them. Claims that rest only on PDFs are marked **Unverified** with a plain link: the 2026 Cabinet decision, the 2008 template, the 2018 Twinning report, AES, Educational Perspectives, BAAU Order 1060 and ADA's fee schedule. I did read these PDFs through `tavily_extract`, and I report what they say, but no footnote vouches for them.
- **HTTP 403 to the checker:** ERES, Educational Perspectives and azertag.az.
- **Not covered:** UK ENIC, Nuffic, anabin and ECE country pages.

## 1. The legal default

- **Current rule (Cabinet of Ministers, 7 January 2026, No. 1, higher education).** **Unverified (PDF):** clause 2.5 reads "Diplomda və diploma əlavədə bütün məlumatlar Azərbaycan dilində yazılır. Məzunun müraciəti ilə təhsil haqqında dövlət sənədləri ingilis dilində də tərtib edilə bilər." Translation: "All information on the diploma and the diploma supplement is written in Azerbaijani. On the graduate's application, state education documents can also be drawn up in English."
  - Clause 2.4.9 lists the language of instruction ("tədris dili") as a field of the supplement.
  - Source: https://nk.gov.az/uploads/doc/docs/695e626203a59.pdf.
  - ENIC-NARIC's page, which the checker can read, states the same default and English-on-application rule.[^2]
- **Electronic issue.** The 7 January 2026 decisions moved state education documents to fully electronic form.[^36] The diploma is prepared automatically about 10 working days after graduation and appears in the myGov cabinet. Paper documents already issued stay valid.[^39] Expect some uploads to be printouts of a system-generated PDF with a barcode.
  - **Source caveat:** the source here is an agency blog (upass.az), not the government.
  - **Unverified:** the generated layout.
- **The 2008 template (Order No. 990, 8 August 2008).**[^37] **Unverified (PDF):** "Diploma əlavə azərbaycan dilində və Avropada geniş yayılmış dillərdən birində (bir qayda olaraq ingilis dilində) doldurulur." Translation: "The supplement is filled in Azerbaijani and in one of the languages widely used in Europe (as a rule, English)." The same template had the supplement issued free at the student's request, and asked institutions to state the language of instruction in full (Azerbaijani, Russian, English…).
- **Bologna.** Azerbaijan joined the Bologna Process in 2005. The 2009 Law on Education introduced the diploma supplement.[^17]
- **Is the supplement automatic? Sources conflict.**
  - ENIC-NARIC says yes.[^38]
  - The 2008 template and the 2018 Twinning report (both PDFs, **Unverified**) say it was issued on request.

  For older graduates, assume some have no supplement, or a blank form. UNEC still offers "filling in the diploma-supplement form for graduates before 2013" (the original Azerbaijani: "2013-cü ilə qədər məzun olanlar üçün diploma əlavə blankının doldurulması").[^18]

## 2. University by university

**English on request, primary source found:**
- **UNEC (Azerbaijan State University of Economics).** Its page says: "Sənədlər tələbənin istəyindən asılı olaraq, azərbaycan və ingilis dillərində verilir." Translation: "Documents are issued in Azerbaijani or English, at the student's choice." English versions have been issued since the 2022/2023 academic year.[^6] UNEC's archive office issues academic transcripts for those who graduated before 2016.[^18]

**English-medium institutions where the transcript language is not stated:**
- **ADA University.** ADA only accepts transfers from programmes taught in English.[^7] The official transcript is ordered through Banner ("Request Printed Transcript").[^19] ADA uses a 4-point GPA.[^21] **Unverified (PDF):** a fee of 10 AZN per transcript, https://www.ada.edu.az/media/2026/06/18/mis_fees.pdf. **Unverified:** that the transcript is English-only.
- **Khazar University.** Instruction is in English.[^9] An official transcript costs 5 AZN per copy.[^22] Khazar has its own grading cut-offs (see §6). **Unverified:** transcript language.
- **Baku Higher Oil School (BHOS).** The registrar issues diplomas with supplements, academic references and transcripts.[^8] The master's engineering programmes are in the English section.[^23] **Unverified:** transcript language.
- **UFAZ (French-Azerbaijani University, part of ASOIU).** Courses are taught in English. Graduates receive one diploma from ASOIU and one from the University of Strasbourg.[^10] Strasbourg grades on a 0–20 scale.[^24] **Unverified:** what language the Strasbourg documents are in.

**No language statement found:** BDU, ADNSU/ASOIU, Azerbaijan Medical University, Azerbaijan Technical University, Baku Engineering University, Azerbaijan University of Languages, Baku Slavic University, Western Caspian University, ADPU and Nakhchivan State University.
- Several of these teach in both Azerbaijani and Russian. BDU's additional-education announcement says: "Təhsil azərbaycan və rus dillərindədir" (instruction is in Azerbaijani and Russian).[^26]
- **Unverified:** an ADPU registrar page, seen in search results but now redirecting to the homepage, said transfer students' academic transcripts are obtained from the Ministry. That would suggest a centrally generated format.

## 3. Russian-sector graduates

**Unverified** that they get a Russian-language transcript. No source says so. The national rule (Azerbaijani, with the language of instruction recorded as a field) points the other way.[^2] Evaluators that list Russian as a document language (ERES, Educational Perspectives; **Unverified**, 403) most likely mean Soviet-era and 1990s documents. Ask launch students for real samples.

## 4. Older graduates (pre-2005, Soviet era)

- Stalin ordered Azerbaijani written in Cyrillic from 1939.[^40] Independent Azerbaijan adopted a Latin alphabet in 1991, with a transition period until 2001 when both scripts were accepted.[^41][^28][^29] A 1990s document can therefore be in Latin Azerbaijani, Cyrillic Azerbaijani or Russian.
- Azerbaijani Cyrillic uses letters Russian lacks: ә, ј, ҹ, ҝ, ғ, ө, ү, һ. The anthem text on Wikipedia shows them.[^42] OCR configured for Russian alone will misread them.
- **Unverified:** AES's note that older documents "may be bilingual in Azeri and in Russian" (PDF).

## 5. What foreign evaluators and universities require

- **uni-assist:** original language plus a German or English translation, attested by an Azerbaijani notary.[^11]
- **WES:** documents in other languages must be translated. Institution-issued English versions are not accepted in place of a translation.[^12]
- **Receiving universities inside Azerbaijan:**
  - ADA requires attachments in English or with a notary-certified English translation.[^31]
  - Khazar's FAQ for international applicants also asks for notarised or apostilled English translations of documents.[^9]
- **ERES, Educational Perspectives, AES:** **Unverified** (403 or PDF). Their pages, read through other tools, list Azerbaijani or Russian as document languages and ask for certified English translations. AES alone notes recent documents may be in English.
- **What this means for the product:** expect most students to upload an Azerbaijani supplement plus a notarised English translation, often as separate files. A minority will have an English transcript from the university (UNEC since 2022/23, and probably the English-medium universities). Even those may need a separate translation for WES.

## 6. Grading scales and labels

| Scale | Where | Labels on the document |
|---|---|---|
| **100-point, A–F (national credit system)** | Most universities (Cabinet decree 348 of 2013 governs the credit system) | 91–100 "əla" A; 81–90 "çox yaxşı" B; 71–80 "yaxşı" C; 61–70 "kafi" D; 51–60 "qənaətbəxş" E; below 51 "qeyri-kafi" F[^33] |
| **Khazar's own scale** | Khazar University | 90–100 A (əla); 80–89 B; 70–79 C; 60–69 D; 0–59 F; "IC" (incomplete) for 57–59[^34] |
| **4-point GPA** | ADA University | "min. 3.0 GPA per semester"[^21] |
| **French 0–20** | UFAZ's Strasbourg diploma | 0 to 20[^24] |
| **Soviet 5-point word grades** | Pre-reform documents | «Əla», «Yaxşı», «Kafi», «Qeyri-kafi», plus pass/fail «Məqbul»/«Qeyri-məqbul». **Unverified (PDF):** the 2008 template, which also says the 100-point system was trialled from 1999. |

- **Unverified (PDF, BAAU copy of Order 1060 of 2008):** that the supplement must show both points and letter for each subject, and that the credit-weighted average ÜOMG (ümumi orta müvəffəqiyyət göstəricisi, overall average performance indicator) appears on the supplement.
- **Unverified:** whether Russian grade words (отлично/хорошо/удовлетворительно) appear on documents from the 1990s and after.

## Table: university → transcript language

| University | Default transcript/DS language | English available? | How | Notes |
|---|---|---|---|---|
| National rule (all) | Azerbaijani[^2] | Yes, on written application[^2] | myGov e-cabinet from 2026[^39] | DS records language of instruction (Unverified, PDF) |
| ADA University | Unverified (English-medium) | Unverified | Banner "Request Printed Transcript"[^19] | 4-pt GPA[^21]; fee 10 AZN Unverified |
| BDU (Baku State) | Unverified (Azerbaijani by law) | Unverified | — | Az + Ru instruction[^26] |
| ADNSU/ASOIU | Unverified | Unverified | — | UFAZ is a sub-unit |
| UNEC | Azerbaijani | **Yes, since 2022/23**[^6] | "Bir Pəncərə" online, QR-coded PDF | Pre-2016 grads via archive[^18] |
| Baku Higher Oil School | Unverified (English-medium) | Unverified | Registrar[^8] | — |
| Khazar University | Unverified (English-medium) | Unverified | Registrar, 5 AZN/copy[^22] | Own A–F cut-offs[^34] |
| Azerbaijan Medical Univ. | Unverified | Unverified | — | — |
| Azerbaijan Technical Univ. | Unverified | Unverified | — | — |
| Baku Engineering Univ. | Unverified | Unverified | — | — |
| Azerbaijan Univ. of Languages | Unverified | Unverified | — | — |
| Baku Slavic Univ. | Unverified | Unverified | — | Likely many Russian-sector grads (Unverified) |
| UFAZ | Az supplement (ASOIU) + Strasbourg diploma[^10] | Unverified | — | 0–20 scale[^24] |
| Western Caspian Univ. | Unverified | Unverified | — | — |
| ADPU (Pedagogical) | Unverified | Unverified | — | — |
| Nakhchivan State Univ. | Unverified | Unverified | — | — |

## What the transcript reader must handle at launch

- **Languages:**
  - Azerbaijani (all state documents)
  - English (on-request versions, notarised translations, English-medium universities)
  - Russian (older and dual-language documents)
  - French (UFAZ's Strasbourg documents), possibly
- **Scripts:**
  - Azerbaijani Latin: ə Ə, ğ, ı/İ, ö, ü, ç, ş, q, x
  - Russian Cyrillic
  - Azerbaijani Cyrillic (ә ј ҹ ҝ ғ ө ү һ) on documents from before about 2001[^41][^42]
- **Document types:**
  - diploma (diplom), which carries no grades
  - diploma supplement (diploma əlavə)
  - academic transcript (akademik transkript)
  - academic reference for incomplete study (akademik arayış)
  - the electronic myGov printout from 2026[^39]
  - older paper supplement booklets
  - the notarised translation as a second file that must be paired with its original
- **Scales:** detect the scale from the labels; do not guess from the numbers. A "C" is 71–80 on the national scale[^33] but 70–79 at Khazar.[^34] A "16" is a 0–20 grade.[^24] A "3.4" is a 4-point GPA.[^21] Always capture the overall average line (ÜOMG/GPA) and the language-of-instruction field.
- **Default assumption:** the student has an Azerbaijani supplement plus a notarised English translation. Treat a university-issued English transcript as the exception.

## Open questions

- From which graduation date does the electronic diploma apply, and what does the TMİS-generated PDF look like? The primary text is a PDF the checker cannot read.
- Do ADA, BHOS, Khazar, BEU and UFAZ issue English transcripts by default? No page states it. Collect three to five real samples.
- Do Russian-sector graduates ever receive Russian-language supplements? No source either way.
- What fee and processing time does any state university other than UNEC charge for an English version?
- Are the Strasbourg documents for UFAZ graduates in French, English or both?
- What do UK ENIC, Nuffic and anabin say? Not reached.

## Sources

[^2]: https://www.enic-naric.net/page-Azerbaijan "Diploma Supplement is issued in Azerbaijani language. However, upon written application of the graduate it can be issued in English."
[^6]: http://unec.edu.az/unec-in-bir-pencere-sistemi-hansi-tehsil-arayislari-almaq-olar/ "Sənədlər tələbənin istəyindən asılı olaraq, azərbaycan və ingilis dillərində verilir."
[^7]: https://www.ada.edu.az/en/admission/undergraduate "Enrolled at an undergraduate program that is taught in English."
[^8]: https://bhos.edu.az/en/page/51/Educational-and-methodological-department "Providing students graduating from BHOS with diplomas (diploma supplements), and, if necessary, duplicates of diplomas, academic references, and academic transcripts"
[^9]: https://international.khazar.org/en/faq "The medium of instruction at Khazar University is English."
[^10]: https://www.ufaz.az/en/about-us/why-ufaz/ "UFAZ students receive two state-recognized diplomas: one from the Azerbaijan State Oil and Industry University (ASOIU) and one from the University of Strasbourg (UNISTRA)"
[^11]: https://www.uni-assist.de/en/tools/info-country-by-country/details-country/country/az/ "We only accept translations from Azerbaijan if an Azerbaijani notary attests the signature and identity of the translator."
[^12]: https://www.wes.org/resource-library/blog/credential-advice/translation-requirements-for-a-wes-credential-evaluation/ "WES cannot accept English- or French-language versions of the documents in place of a translation."
[^17]: https://www.enic-naric.net/page-Azerbaijan "Azerbaijan started the reform of its higher education system by joining the Bologna Process in 2005"
[^18]: https://news.unec.edu.az/elan/10101-telebelerin-nezerine/13691-arxiv-senedi-almag-isteyenlerin-mezunlarin-diggetine "2013-cü ilə qədər məzun olanlar üçün diploma əlavə blankının doldurulması"
[^19]: https://my.ada.edu.az/en/service/students-10.html "click Request Printed Transcript on the Banner Student card"
[^21]: https://www.ada.edu.az/en/admission/undergraduate "must meet min. 3.0 GPA per semester requirement"
[^22]: https://khazar.org/en/item/167 "There is a fee in the amount of equivalent of 5 AZN for each copy of an official transcript."
[^23]: https://bhos.edu.az/page/116/admission-graduate "Bütün ixtisaslar ingilis bölməsi üzrə yerli tələbələr üçün 5000 AZN"
[^24]: https://international-welcome.unistra.fr/apply-to-the-university-of-strasbourg-1/translate-to-english-grille-de-notation-sciences-et-technologies/ "Grading is based on a scale from 0 (minimum) to 20 (maximum)."
[^26]: http://bsu.edu.az/az/news/elan17052018022421 "Təhsil azərbaycan və rus dillərindədir."
[^28]: https://cotsen.blogs.princeton.edu/2017/10/new-nation-new-alphabet-azerbaijani-childrens-books-in-the-1990s/ "the Azerbaijani Parliament voted to adopt a Latin script for the Azerbaijani language, abandoning the Cyrillic script"
[^29]: https://cotsen.blogs.princeton.edu/2017/10/new-nation-new-alphabet-azerbaijani-childrens-books-in-the-1990s/ "Only in 2001 did then president Heydar Aliyev declare"
[^31]: https://www.ada.edu.az/en/admission/undergraduate "All attachments must be submitted either in English or with the notary-certified translation into English."
[^33]: https://rif.baau.edu.az/az/page/akademik-qaydalar-156 "51-60 bal – “qənaətbəxş” - E;"
[^34]: https://khazar.org/az/item/149 "(Natamam). Bu, yalnız 57-59 bal yığmış tələbələrə aiddir."
[^36]: https://upass.az/bloq/elektron-diplom-attestat/ "Nazirlər Kabinetinin 2026-cı il 7 yanvar tarixli qərarları ilə dövlət təhsil sənədləri tam elektron formata keçirildi."
[^37]: https://edu.gov.az/az/esas-senedler/749 "Təhsil naziri 08 avqust 2008-ci il № 990"
[^38]: https://www.enic-naric.net/page-Azerbaijan "The diploma supplement is issued automatically to all students who receive Bachelor"
[^39]: https://upass.az/bloq/elektron-diplom-attestat/ "Sənəd təxminən 10 iş günü ərzində hazır olur"
[^40]: https://en.wikipedia.org/wiki/Azerbaijani_alphabet "ordered the discontinuation of the Azerbaijani Latin script"
[^41]: https://en.wikipedia.org/wiki/Azerbaijani_alphabet "From 1991 to 2001, there was a transitional period, when both Latin and Cyrillic alphabets were accepted."
[^42]: https://en.wikipedia.org/wiki/Azerbaijani_alphabet "Сәндән өтрү ҹан вермәјә ҹүмлә һазырыз!"
