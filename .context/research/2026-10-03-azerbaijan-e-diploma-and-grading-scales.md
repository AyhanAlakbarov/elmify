# Azerbaijani electronic diplomas (2026) and transcript grading scales

Date: 2026-10-03. Purpose: inputs for the transcript reader (OCR → code → classifier) for Azerbaijani launch students.
Status: **stopped early at the step limit.** Several items are marked **Unverified** or moved to Open questions.

## Answer first

- **Since summer 2026, new graduates get an electronic diploma *and* diploma supplement, not paper.** Both are created in TMİS, signed with the rector's qualified e-signature and placed in the graduate's myGov (EHİS) cabinet. The supplement must list every course with its credits (hours), the grades and points, and the ÜOMG (weighted average).[^4][^6][^7][^9][^10] Graduates can download the documents as PDF.[^16] **Unverified:** whether that PDF has a text layer or an embedded PAdES signature, or is just a rendering. No public sample was found.
- **Verification is public, but not machine-friendly.** Each document carries a code: the regulation calls it a *ştrix kod* (barcode),[^8][^30] while the operator (IDDA) and the press say QR code.[^13][^17][^28] edu.gov.az/az/yoxla takes the document number plus the holder's **date of birth** and is behind **reCAPTCHA**.[^18] **Unverified:** what the check returns (the document itself, or only name and number).
- **Older graduates do not get a new e-diploma by default.** Under the rule, a pre-2026 diploma is reissued electronically only as a duplicate, when the original was lost, damaged or destroyed.[^5] IDDA says previous graduates can *view* their diplomas on myGov,[^14] but that may be the older data record and not the signed document plus supplement. See Open questions.
- **National grading (credit system): a 100-point scale with letter bands.** 91–100 A əla, 81–90 B çox yaxşı, 71–80 C yaxşı, 61–70 D kafi, 51–60 E qənaətbəxş, under 51 F qeyri-kafi. Universities publish this scale.[^22] The act that sets it is Ministry of Education order **No. 1060 of 11.09.2008**. **Unverified:** only university copies were seen, as PDFs and search highlights, not the ministry original. Several private universities run their **own** scales: Khazar, BHOS and ADA (below). So the scale must be chosen by institution, not by country.

## Scope (sub-questions)

1. A1: What the 7 Jan 2026 Cabinet decision (No. 1) says about format, signature, verification code, supplement content, delivery channel and transition.
2. A2: The public verification service: its URL, inputs and output.
3. A3: The UNEC "Bir Pəncərə" QR-coded PDF transcript.
4. B1–B4: The national 100-point scale and its legal basis; the pre-credit scale; institution-specific scales; credit units.

## Tools used, and which were missing

- Exa, Brave (web and news), Tavily extract (one lead read of a JavaScript page) and scrapling `get` were all available. Context7 was not relevant.
- **Limits:** e-qanun.az renders by JavaScript, so scrapling returns nothing there. azertag.az returned 403. scrapling `get` on PDFs returns the raw, compressed PDF bytes, so quotes from PDFs below came from Exa highlights and **may fail the automatic citation check**. They are kept because the PDF is the primary legal text and no HTML copy of these clauses was found.

## A1. Cabinet of Ministers Decision No. 1 of 7 January 2026

- **Date typo on the official page.** The Cabinet's own press bulletin dates the decision "2025-ci il 7 yanvar".[^2] The bulletin was published 08.01.2026 and the PDF heading says 2026, so 2025 is a typo.
- **It replaces the 2010 rules.** It repeals Decision No. 82 of 29 April 2010 and approves separate rules for each level.[^4] The higher-education text is "Ali təhsil pilləsinin bakalavriat, əsas (baza ali) tibb təhsili, magistratura və rezidentura səviyyələrində təhsil haqqında dövlət sənədlərinin təsvirləri və onların verilməsi Qaydası" (nk.gov.az PDF).
- **Format.** The diploma, together with its supplement, is an electronic document created in TMİS under the Law "On electronic signature and electronic document".[^4]
  - Original: "elektron sənəd formasında yaradılan müvafiq təhsil haqqında dövlət sənədi - diplom (diploma əlavə ilə birlikdə) veriləcək".
  - Translation: "the state education document, the diploma (together with the diploma supplement), created as an electronic document, will be issued".
- **Signature.** Bachelor's and master's diplomas are approved with the HEI head's "təkmil sertifikatlı gücləndirilmiş elektron imzası" (qualified, enhanced e-signature).[^9] Residency diplomas are signed by the Health Minister. IDDA describes the result as "documents electronically signed and verified by their educational institutions".[^15]
- **Delivery.** Documents are placed in the graduate's electronic cabinet in EHİS.[^10] In practice that cabinet is my.gov.az → "Təhsil" → "Elektron təhsil sənədlərim".[^13] Graduates can share and print the documents.[^3] Downloading as PDF is stated by the Ministry of Digital Development.[^16]
- **No paper copy is issued in parallel.** The State Agency, quoted by modern.az (22.01.2026), said "Təhsil sənədlərinin paralel kağız daşıyıcıda verilməsi nəzərdə tutulmur" ("parallel issuance on paper is not foreseen"). **Unverified:** this was seen only in an Exa highlight and not fetched.
- **Supplement content.** Clause 2.4 lists, among others:
  - 2.4.13: total academic credits.
  - 2.4.17: ÜOMG.[^6]
  - 2.4.18: "tədris planı üzrə fənlərin adı, təcrübə, onlara ayrılan kreditlər (saatlar), yekun dövlət attestasiyasının növü (olduğu halda), təhsilalanın aldığı qiymətlər və ballar". Translation: course names, internships, credits (hours) per course, type of final state attestation, and the grades and points received.[^7]
  - 2.4.22: a barcode to verify the supplement.[^8] The diploma has its own barcode (2.3.11).[^30]
- **Language.** Everything is in Azerbaijani; an English version is issued on the graduate's request.[^11] UNEC certificates, by comparison, have been available in English since 2022/23.[^20]
- **Rollout.**
  - BDU started issuing e-diplomas in July 2026.[^12]
  - The 2026 graduates' documents went live on my.gov.az on 13 Aug 2026; the mobile app was to follow.[^13]
  - Officials said they were seeking implementation in "the second half of the year". **Unverified:** modern.az, 22.01.2026, seen in an Exa highlight only.
- **Transition for existing graduates.** Diplomas issued before the rule took effect are reissued electronically only on application, when lost, damaged or destroyed.[^5] Separately, IDDA says graduates from previous years "can also view their diplomas" on myGov.[^14] The diploma *data* service ("Diplom haqqında məlumatlar") predates 2026, so this is probably the data record, not a signed PDF plus supplement (**Unverified**).

## A2. Public verification service

- **URL:** https://edu.gov.az/az/yoxla ("Elektron sənəd yoxlanışı").[^18]
- **Inputs:** the document number and the holder's date of birth.[^17] The form fields are `documentId` (placeholder "Sənədin identifikasiya nömrəsi (İN)") and `documentFin` (placeholder "Doğum tarixi"), plus a Google reCAPTCHA. This was read from the page HTML (form markup); attribute text may not pass the citation check.
- **Output: Unverified.** The page has "ENDİR / Çap et / Paylaş" (download / print / share) controls, which suggests it returns the document itself. Nothing was submitted, per the brief.
- **QR path.** Scanning the code on the document opens the electronic form of the document.[^13][^28] Whether the QR target URL can be fetched without the date of birth is **Unverified**.
- **Consequence for us:** the CAPTCHA plus the date-of-birth requirement mean automated verification is a human-in-the-loop step or a student-consented one. It is not a background fetch.

## A3. UNEC "Bir Pəncərə" transcripts

- **What is stated.** UNEC issues academic transcripts as PDFs, "approved with signature and seal, with a QR code", to the student's cabinet or email.[^19][^21] The page cites the e-signature law, saying an e-signature equals a sealed hand signature.[^19]
  - Original: "Arayışlar Sizə elektron variantda PDF formatında, QR kodla, imza və möhürlə təsdiqlənmiş nümunədə elektron ünvanınıza göndəriləcəkdir."
  - Translation: "Certificates will be sent to your email in electronic form, as a PDF, with a QR code, approved with signature and seal."
- **Unverified:**
  - whether "imza" here is a cryptographic signature embedded in the PDF, or a scanned signature and seal image;
  - whether the PDF has a text layer;
  - what the QR resolves to.

  No public sample was found.
- **Side note:** birpencere.unec.edu.az currently carries injected French casino spam text. Treat that host as compromised content, and never trust a QR that resolves there without checking the origin.

## B1. National credit-system scale

- **Bands.** The bands in the table below are published by universities, for example the Azerbaijan Medical University course page ("E – «qənaətbəxş» 51-60 bal").[^22]
- **Owning act.** The source is Ministry of Education order No. 1060 of 11.09.2008, "Kredit sistemi ilə təhsil alan tələbələrin biliyinin qiymətləndirilməsi haqqında Əsasnamə".
  - Copies seen as PDFs: baau.edu.az, mdu.edu.az (`Emr-1060.pdf`). ADU's assessment page cites "(Əmr 1060, 11.09.2008)".
  - That order says points **and** letter marks must be written in supplements and other documents: "diplomlara əlavələrdə ... ballar və onların hərf işarələri qeyd olunmalıdır".
  - **Unverified:** seen via Exa highlights of PDFs only.
- **Points composition.** Normally 50 points from the semester and 50 from the exam. **Unverified**, from the same order copies.
- **Framework act.** The credit system itself is Cabinet Decision **No. 348 of 24.12.2013**, amended, among others, by No. 257 of 14.06.2017 (cited by AzTU) and No. 167 of 2019.
  - In 348, an academic transcript is "kreditləri və qiymətləri (rəqəm və hərflərlə)", i.e. credits and grades in numbers and letters.
  - ÜOMG is defined there (2.1.14).
  - **Unverified:** e-qanun.az/framework/27030 is JavaScript-only; this was read via Tavily extract.
  - No band table was found in 348 itself.
- **Conflicting source, flagged.** azedu.az (a news site, not an owner) swaps the words: "51-60 bal (E) kafi, 61-70 bal (D) qənaətbəxş". Every university copy of order 1060 and every university page seen says E = qənaətbəxş and D = kafi. Follow the order. Have the reader treat the *word* as secondary to the *number*.
- **ÜOMG formula** (order 1060 copies; **Unverified** as above):
  - ÜOMG = Σ(bᵢ·kᵢ\*) / Σkᵢ, where bᵢ is the points in course i, kᵢ its planned credits, and kᵢ\* the credits earned (0 if failed).
  - So a failed course stays in the denominator. Khazar, by contrast, excludes F from its GPA.[^25]
- **ÜOMG is printed on the supplement** under the 2026 rule.[^6]

## B2. Pre-credit scales

- **Four words.** A 1997 Ministry order (No. 54, 27.01.1997, state attestation) grades with "əla", "yaxşı", "kafi", "qeyri-kafi" (e-qanun.az/framework/10328; **Unverified**, JavaScript page, Exa highlight).
- **Pass/fail words.** The Ministry's 2008 diploma-supplement template (order No. 990, 08.08.2008) describes the system as «Əla», «Yaxşı», «Kafi» positive; «Qeyri-kafi» negative; «Məqbul» positive and «Qeyri-məqbul» negative (the pass/fail pair).
- **An older experimental 100-point scale.** The same template adds: "1999-cu ildən eksperiment şəklində çoxballı sistem tətbiq olunur: 0-50 qeyri-kafi, 51-70 kafi, 71-85 yaxşı, 86-100 əla". Source: edu.gov.az/upload/file/diploma-elave-numunesi.pdf, **Unverified** (PDF, Exa highlight only).
  - **This is a different 100-point banding from 2008+.** A score of 86 is "əla" on a 1999–2008 supplement but "B / çox yaxşı" under order 1060.
- **Numeric 5/4/3/2 marks** and the Russian words (отлично / хорошо / удовлетворительно / неудовлетворительно, зачёт / незачёт), and the term "keçdi": **Unverified.** These are standard post-Soviet usage, but no Azerbaijani primary text was fetched.

## B3. Institution-specific scales

- **Khazar University** uses its own 100-point bands with different word mapping. Its undergraduate scale is 90–100 A əla, 80–89 B yaxşı, 70–79 C orta/qənaətbəxş, 60–69 D kafi, 0–59 F.[^23][^24] Master's has a D+ low pass at 65–69.[^26] The GPA is the credit-weighted mean on the 100-point scale, rounded to a whole number.[^25] **Unverified:** honours at 90–93 / 94–97 / 98–100 (khazar.org/en/item/155, Exa highlight only).
- **BHOS** uses 91–100 A, 81–90 B, 71–80 C, 61–70 D, ≤60 F, and **has no E band**: "The minimum passing grade is 61 points (D)".[^27] The cited page is the MBA curriculum page; the bachelor's module handbooks state the same scale (PDF). Course credits are labelled ECTS (for example 7.5 per MBA course).[^27]
- **ADA University** grades on a US-style 4.0 scale: A 4.00 94–100, A− 3.67 90–93, B+ 3.33 87–89, B 3.00 83–86, B− 2.67 80–82, C+ 2.33 77–79, C 2.00 73–76, C− 1.67 70–72, D+ 1.33 67–69, D 1.00 60–66, F 0.00 0–59, FX 0.00 (administrative fail). Raw scores are rounded to an integer before the letter is assigned.
  - The term GPA is credit-weighted grade points; pass/fail courses are excluded and only the highest grade of a repeated course counts.
  - Honours for state diplomas need a cumulative GPA of at least 3.80.
  - **Unverified for the citation check:** ada.edu.az publishes this only as PDFs (`student_assessment_regulations.pdf`, 2025; Academic Catalogues), seen via Exa highlights.
- **UFAZ** awards double diplomas from ASOIU and the University of Strasbourg (ufaz.az "Why UFAZ", Exa highlight). The French 0–20 scale on the Strasbourg diploma (pass mark 10/20) is **Unverified**; no UFAZ grading page was fetched.
- **Open:** whether the ADA, Khazar or BHOS state *supplement* (TMİS) prints the institution's own scale or a mapping to the national bands.

## B4. Credit units

- **Credit totals.** National credits: bachelor 240–300 (basic medical 300–360); master 90 for 1.5 years or 120 for 2 years. Per Decision 348 §3.2.4 as reproduced by GDU and AzTU: **Unverified** (PDF / JavaScript only).
- **ECTS alignment.** The Ministry's 2014 comparison note says the new rules set 30 credits per semester and 60 per year to meet ECTS requirements (edu.gov.az/upload/file/yukleme/2014/qaydalarin_ustunlekleri.pdf, **Unverified**, Exa highlight). So 1 Azerbaijani credit is meant to equal 1 ECTS.
- **Older documents differ.** Pre-2014 documents used other credit counts (200–250 per degree under the 2006 model regulation, **Unverified**). The 2008 supplement template shows hours alongside credits.
- **On the 2026 supplement**, credits are printed per course "(saatlar)" (or hours) and in total.[^7]

## Scale tables for code

Encode each scale as data, keyed by `(institution, document_era)`. The reader must pick the scale from the issuer and date, never from the grade values alone, because 86 and 60 mean different things on different scales.

### T1. National credit system (order 1060 of 2008; default for state HEIs, 2008 onwards)

| points (incl.) | letter | az | ru (Unverified) | en | pass |
|---|---|---|---|---|---|
| 91–100 | A | əla | отлично | excellent | yes |
| 81–90 | B | çox yaxşı | очень хорошо | very good | yes |
| 71–80 | C | yaxşı | хорошо | good | yes |
| 61–70 | D | kafi | удовлетворительно | satisfactory | yes |
| 51–60 | E | qənaətbəxş | посредственно / достаточно | sufficient | yes |
| 0–50 | F | qeyri-kafi | неудовлетворительно | fail | no |

ÜOMG is a 0–100 credit-weighted mean; failed credits count as 0 in the numerator.

### T2. Pre-credit / Soviet-legacy word scale (numeric column Unverified)

| mark | az | ru | en | pass |
|---|---|---|---|---|
| 5 | əla | отлично | excellent | yes |
| 4 | yaxşı | хорошо | good | yes |
| 3 | kafi | удовлетворительно | satisfactory | yes |
| 2 | qeyri-kafi | неудовлетворительно | fail | no |
| P | məqbul (keçdi: Unverified) | зачёт | pass | yes |
| NP | qeyri-məqbul | незачёт | fail | no |

### T3. Experimental 100-point scale on 1999–2008 supplements (Unverified, 2008 template)

| points | az | en | pass |
|---|---|---|---|
| 86–100 | əla | excellent | yes |
| 71–85 | yaxşı | good | yes |
| 51–70 | kafi | satisfactory | yes |
| 0–50 | qeyri-kafi | fail | no |

### T4. Khazar University

| level | points | letter | az | en | pass |
|---|---|---|---|---|---|
| bachelor | 90–100 | A | əla | excellent | yes |
| bachelor | 80–89 | B | yaxşı | good | yes |
| bachelor | 70–79 | C | orta / qənaətbəxş | average/satisfactory | yes |
| bachelor | 60–69 | D | kafi | low pass | yes |
| bachelor | 0–59 | F | qeyri-kafi | failure | no |
| master | 65–69 | D+ | – | low pass | yes |
| master | 0–64 | F | – | failure | no |
| PhD | 0–69 | F | – | failure | no |

Special marks: IC (incomplete, 57–59) and IP (in progress); both are excluded from the GPA. The GPA is an integer on the 0–100 scale.

### T5. BHOS

| points | letter | en | pass |
|---|---|---|---|
| 91–100 | A | excellent | yes |
| 81–90 | B | very good | yes |
| 71–80 | C | good | yes |
| 61–70 | D | satisfactory | yes |
| 0–60 | F | failure | no |

### T6. ADA University (Unverified for the citation check; ADA PDFs)

| letter | points | % | descriptor | pass |
|---|---|---|---|---|
| A | 4.00 | 94–100 | excellent | yes |
| A− | 3.67 | 90–93 | | yes |
| B+ | 3.33 | 87–89 | | yes |
| B | 3.00 | 83–86 | good | yes |
| B− | 2.67 | 80–82 | | yes |
| C+ | 2.33 | 77–79 | | yes |
| C | 2.00 | 73–76 | satisfactory | yes |
| C− | 1.67 | 70–72 | | yes |
| D+ | 1.33 | 67–69 | poor | yes |
| D | 1.00 | 60–66 | poor | yes |
| F | 0.00 | 0–59 | academic fail | no |
| FX | 0.00 | 0 | administrative fail | no |

### T7. UFAZ Strasbourg diploma (Unverified)

French 0–20 scale; pass at ≥10/20.

## What the reader can rely on

1. **2026+ graduates (state documents from TMİS).**
   - The source is a myGov-issued electronic diploma plus supplement, downloadable as PDF and signed by the institution head's qualified e-signature.[^9][^16]
   - The supplement must carry the per-course name, credits, points and grade, plus the ÜOMG.[^6][^7]
   - **Plan:** try PDF text extraction first and fall back to OCR only if no text layer is found. Do not assume a text layer until one real sample is checked: that, and whether the signature is embedded PAdES, are both **Unverified**.
2. **Authenticity.** Each document has a verification code (barcode or QR).[^8][^13] The official check needs document number plus date of birth behind reCAPTCHA.[^17][^18] The reader cannot verify silently. Two options:
   - with the student's consent, the system uses the QR target / edu.gov.az check;
   - or a counsellor clicks through.

   Validating an embedded signature in the PDF would be the automatable path, if one exists (**Unverified**).
3. **Pre-2026 graduates (the large majority of launch students).**
   - Expect paper diplomas with scanned supplements, so OCR is required. The rule gives them a new e-document only as a duplicate after loss or damage.[^5]
   - Expect UNEC-style university PDFs with a QR code and a "signature and seal" for transcripts.[^19] These may be text PDFs or scans (**Unverified**).
   - myGov may show their diploma *data*.[^14]
4. **Grades: never infer the scale from the values.**
   - Choose T1, T3, T4, T5 or T6 by issuer and date.
   - Supplements under order 1060 print both points and letters, so cross-check the letter against the band and flag a mismatch.
   - Treat the Azerbaijani word as the weakest signal: Khazar's "yaxşı" is B, the national "yaxşı" is C, and one news site even swaps kafi and qənaətbəxş.

## Sources

[^2]: https://nk.gov.az/az/xeberler/matbuat-xidmatinin-bulletenlari/tehsil-haqqinda-dovlet-senedlerinin-elektron-forma-3451 "Azərbaycan Respublikası Nazirlər Kabinetinin 2025-ci il 7 yanvar tarixli 1 nömrəli Qərarına əsasən"
[^3]: https://nk.gov.az/az/xeberler/matbuat-xidmatinin-bulletenlari/tehsil-haqqinda-dovlet-senedlerinin-elektron-forma-3451 "Məzunlar sənədlərini elektron kabinetlərindən istənilən vaxt əldə edə, elektron qaydada paylaşa və zərurət olduqda çap edə biləcəklər"
[^4]: https://axar.az/news/toplum/1050312.html "elektron sənəd formasında yaradılan müvafiq təhsil haqqında dövlət sənədi - diplom (diploma əlavə ilə birlikdə) veriləcək"
[^5]: https://axar.az/news/toplum/1050312.html "diplomalanın müraciətinə əsasən elektron sənəd formasında yaradılan diplomun dublikatı veriləcək"
[^6]: https://nk.gov.az/uploads/doc/docs/695e626203a59.pdf "ümumi orta müvəffəqiyyət göstəricisi (ÜOMG)"
[^7]: https://nk.gov.az/uploads/doc/docs/695e626203a59.pdf "tədris planı üzrə fənlərin adı, təcrübə, onlara ayrılan kreditlər (saatlar)"
[^8]: https://nk.gov.az/uploads/doc/docs/695e626203a59.pdf "diploma əlavənin həqiqiliyini yoxlamaq üçün ştrix kod"
[^9]: https://nk.gov.az/uploads/doc/docs/695e626203a59.pdf "təkmil sertifikatlı gücləndirilmiş elektron imzası ilə təsdiq edilir"
[^10]: https://nk.gov.az/uploads/doc/docs/695e626203a59.pdf "diplomalanın EHİS-dəki elektron kabinetində"
[^11]: https://nk.gov.az/uploads/doc/docs/695e626203a59.pdf "Diplomda və diploma əlavədə bütün məlumatlar Azərbaycan dilində yazılır"
[^12]: https://muallim.edu.az/ali-tehsil-pillesinde-mezunlara-elektron-diplomlarin-verilmesine-baslanilib "artıq Bakı Dövlət Universitetinin məzunlarına elektron diplomların verilməsinə başlanılıb"
[^13]: https://idda.az/en/news/electronic-education-documents-of-2026-graduates-are-now-available-on-the-mygov-platform "users can scan the QR code displayed on the document with a camera"
[^14]: https://idda.az/en/news/electronic-education-documents-of-2026-graduates-are-now-available-on-the-mygov-platform "Graduates from previous years can also view their diplomas through the platform."
[^15]: https://idda.az/en/news/electronic-education-documents-of-2026-graduates-are-now-available-on-the-mygov-platform "documents electronically signed and verified by their educational institutions"
[^16]: https://mincom.gov.az/en/media-en/news/mygov-digital-educational-documents-now-have-full-legal-force "download documents in PDF format"
[^17]: https://az.trend.az/azerbaijan/society/4214877.html "sənədin nömrəsi və doğum tarixini daxil etmək mümkündür"
[^18]: https://edu.gov.az/az/yoxla "Yoxlamaq istədiyiniz sənədin üzərində olan məlumatları aşağıda daxil edin."
[^19]: https://birpencere.unec.edu.az/index.php/az/ "Arayışlar Sizə elektron variantda PDF formatında, QR kodla, imza və möhürlə təsdiqlənmiş nümunədə elektron ünvanınıza göndəriləcəkdir."
[^20]: https://unec.edu.az/unec-in-bir-pencere-sistemi-hansi-tehsil-arayislari-almaq-olar/ "İngilis dilində arayışlar 2022/2023-cü tədris ilindən verilməyə başlanılıb."
[^21]: https://unec.edu.az/unec-in-bir-pencere-sistemi-hansi-tehsil-arayislari-almaq-olar/ "Hazırlanmış sənəd imza və möhürlə təsdiq olunaraq, QR kodla PDF formatında tələbənin şəxsi kabinetinə göndərilir."
[^22]: https://amu.edu.az/page/1999 "E – «qənaətbəxş» 51-60 bal"
[^23]: https://khazar.org/az/item/149 "“80-89” bal “B” (yaxşı)"
[^24]: https://khazar.org/az/item/149 "“70-79” bal “C” (orta və ya qənaətbəxş)"
[^25]: https://khazar.org/en/item/149 "The G.P.A. is rounded to the nearest whole number."
[^26]: https://khazar.org/en/item/149 "the letter grade D+, specifically, “65-69”, is for low pass"
[^27]: https://bhos.edu.az/en/page/113/curriculum-structure-mba "The minimum passing grade is 61 points (D)"
[^28]: https://modern.az/az/tehsil/785002/elektron-diplom-alanlarin-diqqetine-kagiz-variantla-bagli-aciqlama "Diplomların üzərində QR kodlar yerləşdirilib."
[^30]: https://nk.gov.az/uploads/doc/docs/695e626203a59.pdf "diplomun həqiqiliyini yoxlamaq üçün ştrix kod"

Footnotes 6–11 and 30 point at the Cabinet's own PDF, the primary text. The quotes were taken from Exa's extraction of that PDF, because scrapling returns the compressed bytes, so these may fail the automatic check. Footnote 28 is a news site reporting an expert's statement, not an owner source.

## Open questions

1. **Is the myGov PDF text-extractable, and does it embed a PAdES/XAdES signature?** Settle it with one real 2026 diploma and supplement from a consenting graduate. This decides whether OCR can be skipped.
2. What does the edu.gov.az/yoxla check (and the QR target) return: the full supplement with courses and grades, or only identity and number? Does the QR link work without the date of birth?
3. Do pre-2026 graduates see a signed diploma *and supplement* in myGov, or only a data record? Can they request an electronic reissue without a loss claim?
4. Order 1060 (2008) has not been read in an official ministry copy, and it is not known whether it was superseded after 2013/2017. Check e-qanun.az in a browser.
5. ADA, Khazar, BHOS: does the TMİS state supplement print the institution scale or the national bands?
6. UFAZ's Strasbourg-side grading and transcript format.
7. Russian-sector documents: the exact Russian terms printed on Azerbaijani supplements, and whether "keçdi" or "məqbul" is used for pass/fail.
8. **Implementation date** of the 2026 rule (entry into force versus "second half of 2026"), and whether 2025 graduates are covered.
