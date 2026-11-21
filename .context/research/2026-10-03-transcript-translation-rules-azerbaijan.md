# Transcript and diploma translation rules for Azerbaijani graduates, by destination and scholarship

Date: 2026-10-03. Scope: master's/PhD and scholarship applications from Azerbaijan. Covers what language the transcript and diploma must be in, what kind of translation is accepted, what legalisation is needed, and whether an English transcript from the Azerbaijani university is enough.

## Method and tools

- Sub-questions: (1) the language and translation rule per destination or scholarship; (2) who may translate (sworn, notarised, certified, issuing university); (3) apostille or consular legalisation for Azerbaijan; (4) whether an English document from the issuing university replaces a translation; (5) destinations that need their own language even for English-taught study.
- Discovery used Exa (`web_search_exa`, plus `web_search_advanced_exa` with `includeDomains` to stay on the owner's site). Brave was available but not needed. Context7 does not apply to this topic.
- Pages were read live with scrapling `get`. **scrapling returns nothing for PDFs**, so four PDFs (Stipendium Hungaricum guide, GKS guideline, MEXT guideline, Türkiye Scholarships Freshers Guide) and the Georgian NCEQE site, which drops scrapling's TLS connection, were read with `tavily_extract`. Citations to those pages may fail the automatic check because the checker cannot read the page, not because the quote is wrong.
- Unreachable: `graduatestudies.kau.edu.sa` (DNS failure), `egov.kz` (redirects to the home page), `e-qanun.az` (empty JavaScript shell), `mes.gov.ge` (TLS refused), and WES's Azerbaijan required-documents page (login required).

## 1. Azerbaijan and the Apostille Convention (confirmed)

- Azerbaijan acceded to the Apostille Convention. The HCCH depositary page records objections from other states and their withdrawal.[^1]
- **Germany objected until 2026.** Germany withdrew its objection, so the Convention has applied between Germany and Azerbaijan only since 16 March 2026.[^2] Before that date, Azerbaijani documents for Germany needed consular legalisation. Any older advice that says Germany needs consular legalisation is out of date.
- Belgium's objection arrived after the deadline and has no legal effect.[^3] The Netherlands withdrew its objection in 2010.[^1]
- Azerbaijan has two apostille authorities: the **Ministry of Justice** for notarial documents, and the **Ministry of Foreign Affairs** for other documents.[^4] In practice the diploma or transcript is apostilled by the MFA, and a notarised translation is apostilled by the Ministry of Justice. The Italian Embassy in Baku describes exactly this two-step flow.[^5]
- **Exact entry-into-force date of the Convention for Azerbaijan: Unverified.** The HCCH status table (cid=41) returned an empty page through scrapling.
- **CIS exemption (Minsk Convention of 22.01.1993).** Russia lists Azerbaijan among the parties to this convention. Under it, documents are accepted with no legalisation at all.[^6] KIMEP (Kazakhstan) says the same for education documents from CIS countries other than Georgia.[^7]

## 2. Per destination and scholarship

### Germany (uni-assist; DAAD)
- Upload the education certificates **and the transcript** in the original language, plus a German or English translation.[^8]
- If the country issues the certificates officially in German or English as well, no translation is needed. Exceptions are listed per country.[^8]
- uni-assist accepts translations only from sworn or court-admitted translators, or from an authorised department of the issuing school or university.[^9]
- **Rule specific to Azerbaijan:** uni-assist accepts a translation from Azerbaijan only if an Azerbaijani notary confirms the translator's signature and identity. This also applies to translations made by a translation agency.[^10] For Azerbaijan, uni-assist wants the diploma and the Diploma Supplement in the original language **and** in German or English translation.[^11]
- DAAD scholarships: **Unverified.** Not researched in this pass. DAAD application documents usually follow the host university or portal.

### Hungary (Stipendium Hungaricum)
- The scheme requires "an official, notarized translation" of every document not originally written in English, Hungarian or the language of the chosen programme. The original must be uploaded together with the translation.[^12] An Azerbaijani or Russian transcript therefore needs a notarised English (or Hungarian) translation. An English original needs no translation.

### Turkey (Türkiye Bursları; YÖK)
- **Applying:** the TBBS upload list names the diploma and transcript but sets no translation requirement for the application stage.[^13]
- **After the award:** at the embassy, at contract signing and at enrolment, the transcript needs a "Turkish translation certified by notary public or Turkish foreign missions".[^14] The diploma, transcript and passport must be "translated into Turkish by institutions/bodies accredited by the Turkish Embassy/ Consulate".[^15] So the scholarship can be applied for with the original documents, but Turkish is required later even for English-taught programmes.
- **YÖK denklik (equivalence):** a foreign national applying for a master's or PhD outside clinical health fields does **not** need equivalence. A "Tanıma Yazısı" (recognition letter) is enough.[^16] Where equivalence is needed, YÖK requires the original diploma and transcript **plus a Turkish translation certified by a Turkish notary or a Turkish mission**.[^17]

### Russia (government quota; recognition)
- Legalisation: documents from Minsk-Convention states, Azerbaijan included, are accepted without legalisation.[^6]
- In Russia, translations are certified by a **notary**.[^18] A Russian university's admissions page lists notarised Russian translations of the diploma and the transcript for recognition.[^19]
- Recognition and nostrification: RosNOU says recognition through Glavexpertcentr has been mandatory since 2019.[^20] **Not settled for Azerbaijan.** Azerbaijan and Russia signed a mutual-recognition agreement on education documents in 2002 (Azerbaijani ratification law 455-IIQ), and recognition is generally not required where such an agreement applies. The official texts (e-qanun.az, nic.gov.ru agreements list) could not be fetched, so this is **Unverified**. The legal owner is Rosobrnadzor/Glavexpertcentr, not a university page.
- Quota application on education-in-russia.com: the portal is JavaScript-only. Whether the quota stage itself needs a Russian translation of the transcript is **Unverified**. The portal's user guide refers only to a notarised Russian translation of the passport.

### United Kingdom (Chevening; universities)
- **Chevening:** transcripts do not need to be translated.[^21] The degree certificate must be the original document, and it does not need to be translated into English.[^22]
- **Universities (typical rule):**
  - Oxford needs the original transcript **and** an English translation. The translation must be issued and stamped by the institution, or certified by a professional translator or notary. A translation without the original is rejected.[^23]
  - UCL needs a translation by the institution or a registered translator, and says "You must not translate the documents yourself."[^24]
  - Edinburgh accepts a translation from the awarding institution, a sworn translator, or a member of ITI.[^25]

### United States (WES; Fulbright)
- WES (US) requires translations of documents not in English.[^26]
- **WES does not accept an English version issued by the institution in place of a translation.** It wants an independent translation of the original.[^27]
- The translation must be word-for-word and made by a professional translator.[^28]
- **Fulbright (U.S. Embassy Baku):** either a certified English translation, or verified copies of the original transcript and degree certificate.[^29] Nominated candidates must later submit a copy of the original transcript "bearing all official, notarized stamps".[^30]

### South Korea (GKS)
- Documents in a language other than English or Korean need a certified translation. The apostille or consular confirmation may go on either the original or the certified translation.[^31]
- A document already printed in both the original language and English needs no further translation.[^32]

### Japan (MEXT)
- Documents must be in Japanese or English. Otherwise a Japanese or English translation is attached.[^33] The guideline sets no translator qualification.

### China (CSC)
- Diplomas and transcripts in languages other than Chinese or English need **notarised** Chinese or English translations. The highest diploma must also be notarised.[^34]

### Italy (Dichiarazione di valore / CIMEA)
- The Italian Embassy in Baku requires the diploma and transcript to be translated **into Italian (not into English)**. The original is apostilled by the MFA, and the translation is apostilled by the Ministry of Justice.[^5]
- Where the university allows it, a CIMEA statement can replace the Dichiarazione di valore.[^35]
- The ministry portal lists "traduzione legale in italiano" (a certified translation into Italian) as an input to the Dichiarazione di valore.[^36]

### France (Campus France / Études en France)
- Campus France Azerbaïdjan asks for "diplômes, annexes et relevés de notes" (diplomas, supplements and transcripts) from the last three years.[^37] The Azerbaijan page does **not** state a translation rule. **Unverified for Azerbaijan.** Campus France offices in Turkey and Tunisia require translation into French by a *traducteur assermenté* (sworn translator), and the Turkey office accepts English documents for English-taught programmes. That is a lead only, not a source for Azerbaijan.

### Netherlands (Nuffic / IDW)
- A diploma not in Dutch, English, German or French must be translated by a sworn translator.[^38]

### Poland
- Documents must carry an apostille or be legalised, and be translated by a sworn translator into Polish, or into English for English-taught programmes.[^39]
- Translations certified by a notary are **not** accepted.[^40] An apostille must itself be translated.[^41]
- Diplomas from outside the EU, OECD and EFTA (Azerbaijan included) need an individual NAWA recognition statement unless a bilateral agreement covers them.[^42] Whether a Poland–Azerbaijan agreement exists is **Unverified**.

### Czechia
- Documents must be officially translated into Czech or English by a Czech sworn translator.[^43] Documents issued in English need no translation.[^44]

### Kazakhstan
- Education documents from CIS countries other than Georgia need no apostille or legalisation.[^7]
- They are translated into Kazakh or Russian and notarised by a notary in Almaty.[^45]

### Georgia
- Every foreign-language document needs a notarised translation into Georgian for recognition by NCEQE (the national recognition centre).[^46]

### Gulf states
- **UAE:** degree equivalency requires a "Certified translation of non-Arabic and English certificates", plus an embassy letter for most countries.[^47]
- **Qatar University:** transcripts not in Arabic must be officially translated into English.[^48]
- **Saudi Arabia: Unverified.** KAU's page was unreachable.

### Erasmus Mundus joint master's (typical consortium rule)
- QEM: documents must be in English or carry "an official certified English translation".[^49] Rules vary by consortium, so read each programme's page.

## 3. Original plus translation, or an English transcript alone?

Rules for whether an English transcript from the Azerbaijani university is accepted on its own:

| Rule | Who applies it |
|---|---|
| **English original is accepted alone** | uni-assist, if the country issues documents officially in English;[^8] GKS, for a bilingual document;[^32] Czechia;[^44] Stipendium Hungaricum;[^12] MEXT;[^33] CSC;[^34] Nuffic;[^38] Chevening (no translation needed at all)[^21] |
| **Original-language document plus translation, always** | WES (an English version is not accepted in place of a translation);[^27] Oxford (a translation without the original is rejected);[^23] UCL (two separate uploads)[^24] |
| **The issuing university may make the translation itself** | uni-assist (authorised department of the issuing university);[^9] Oxford;[^23] UCL;[^24] Edinburgh[^25] |

## 4. Destinations that need their own language even for English-taught study

- **Turkey:** Turkish notarised translation for the Türkiye Scholarships contract and enrolment,[^14] and for YÖK equivalence.[^17]
- **Italy:** Italian, "not into English", for the Dichiarazione di valore.[^5]
- **Russia:** notarised Russian translation for recognition.[^19]
- **Kazakhstan:** Kazakh or Russian.[^45]
- **Georgia:** Georgian.[^46]
- **Poland:** Polish for Polish-taught programmes; English is accepted for English-taught ones.[^39]
- **France:** probably French (sworn translator). **Unverified** for Azerbaijan.

## Summary table

| Destination / scholarship | Accepted languages | Translation type required | Legalisation from Azerbaijan | Azerbaijani university's own English transcript enough? | Source |
|---|---|---|---|---|---|
| Germany – uni-assist | Original + German or English | Sworn/court-admitted or issuing university; **Azerbaijani notary must confirm translator** | Apostille since 16 Mar 2026 (when required) | Yes if officially issued in English (country exceptions apply) | [^8][^9][^10][^2] |
| Hungary – Stipendium Hungaricum | English, Hungarian, programme language | Official, notarised | Not required at application | Yes | [^12] |
| Turkey – Türkiye Bursları | Application: original; award/enrolment: Turkish | Notary-certified Turkish, or by Turkish mission | Embassy-approved | At application yes; Turkish needed later | [^13][^14][^15] |
| Turkey – YÖK denklik | Turkish | Turkish notary or Turkish mission | — | No (not needed for foreign master's/PhD, non-clinical) | [^16][^17] |
| Russia – quota / recognition | Russian | Notarised Russian | None (Minsk Convention) | No | [^6][^18][^19] |
| UK – Chevening | Any | None | None | Yes (no translation needed) | [^21][^22] |
| UK – universities (Oxford/UCL/Edinburgh) | Original + English | Issuing institution, professional/sworn, notary-certified | None stated | Accepted as the translation, uploaded with the original | [^23][^24][^25] |
| USA – WES | Original + English | Professional, word-for-word, independent | — | **No** | [^26][^27][^28] |
| USA – Fulbright (Baku) | English | Certified translation or verified copies | Notarised stamps for nominees | Unclear | [^29][^30] |
| South Korea – GKS | English or Korean | Certified translation | Apostille on original or translation | Yes if bilingual | [^31][^32] |
| Japan – MEXT | Japanese or English | Translation (no qualifier) | — | Yes | [^33] |
| China – CSC | Chinese or English | Notarised translation; diploma notarised | — | Yes (diploma still notarised) | [^34] |
| Italy – DV / CIMEA | Italian (not English) | Translation apostilled by MoJ | Apostille (MFA) on original | No | [^5][^35][^36] |
| France – Campus France | Unverified (likely French; English for English-taught) | Unverified (sworn translator elsewhere) | Unverified | Unverified | [^37] |
| Netherlands – Nuffic | Dutch, English, German, French | Sworn translator | — | Yes | [^38] |
| Poland | Polish; English for English-taught | Sworn translator; notary-certified rejected | Apostille or legalisation | Unclear (diploma must also be translated if apostille not in Polish) | [^39][^40][^41][^42] |
| Czechia | Czech or English | Czech sworn translator | Apostille / treaty (CTU list) | Yes | [^43][^44] |
| Kazakhstan | Kazakh or Russian | Notarised in Kazakhstan | None (CIS) | No | [^7][^45] |
| Georgia | Georgian | Notarised | Unverified | No | [^46] |
| UAE | Arabic or English | Certified | Embassy letter | Yes | [^47] |
| Qatar – QU | Arabic or English | Official translation | Unverified | Yes | [^48] |
| Saudi Arabia | Unverified | Unverified | Unverified | Unverified | — |
| Erasmus Mundus (QEM example) | English | Official certified | Consortium-specific | Yes | [^49] |

## What the product must tell the student

Rules the document checklist can apply:

1. **Find the transcript's language first.** Record `az`, `ru`, `en` or bilingual. Many destinations exempt English or bilingual originals, but WES never does.[^27]
2. **WES / US credential evaluation:** always the original-language document plus an independent professional word-for-word translation, even if the university issued an English copy.[^27][^28]
3. **Germany via uni-assist:** a German or English translation by a sworn translator or the issuing university, with an Azerbaijani notary confirming the translator. A plain agency translation fails.[^10]
4. **Italy:** an Italian translation (not English). Apostille the original at the MFA and the translation at the Ministry of Justice. Alternatively a CIMEA statement, if the university allows it.[^5][^35]
5. **Turkey with Türkiye Bursları:** apply with the originals. Plan a Turkish translation, notarised or certified by a Turkish mission, before the contract and enrolment.[^14] Foreign master's/PhD applicants do not need YÖK equivalence (non-clinical fields).[^16]
6. **Russia, Kazakhstan:** no apostille for Azerbaijani documents (CIS Minsk Convention).[^6][^7] Kazakhstan needs a Kazakh or Russian translation notarised in Kazakhstan.[^45] Russia needs notarised Russian translations for recognition.[^19]
7. **Poland:** a sworn translator only. A notary-certified translation is rejected,[^40] and the apostille must be translated too.[^41] Flag the NAWA recognition statement for Azerbaijani diplomas.[^42]
8. **Hungary (Stipendium Hungaricum):** a notarised translation only when the original is not English, Hungarian or the programme language.[^12]
9. **CSC (China):** notarised translation plus a notarised diploma.[^34] **GKS (Korea):** certified translation plus apostille (on the original or the translation).[^31] **MEXT (Japan):** an English or Japanese translation is enough.[^33]
10. **UK:** Chevening needs no translation.[^21][^22] UK universities need the original plus a translation by the institution or a sworn/professional translator, and never the student's own.[^23][^24][^25]
11. **Georgia, Netherlands, Czechia, Gulf:** Georgian notarised;[^46] Dutch-system sworn translator unless Dutch/English/German/French;[^38] Czech sworn translator unless English;[^44] UAE/Qatar accept English, otherwise a certified translation.[^47][^48]
12. **Always show "check the programme page".** Universities and consortia set their own rules within these national frames (Erasmus Mundus, UK, Poland).

## Open questions

- Russia: does the 2002 Azerbaijan–Russia mutual-recognition agreement remove the need for Glavexpertcentr recognition for master's entry? RosNOU's page says recognition is always mandatory; the agreement owner (Rosobrnadzor/nic.gov.ru agreements list) was not fetched.
- Russia quota (education-in-russia.com): which translations are required at the application stage versus on arrival? The portal is JavaScript-only.
- France: Campus France Azerbaïdjan's translation rule (sworn French translator? English accepted?). Not stated on the fetched page.
- Poland: is there a Poland–Azerbaijan education recognition agreement that removes the NAWA statement?
- Saudi Arabia (KAU, Study in Saudi): language and attestation rules. The source was unreachable.
- Czechia: CTU's "List of states – required verification of diplomas" entry for Azerbaijan (apostille or treaty).
- DAAD scholarship document rules were not researched.
- The exact Apostille Convention entry-into-force date for Azerbaijan, and whether uni-assist now asks for an apostille on Azerbaijani documents after Germany's 16 March 2026 withdrawal.
- WES's Azerbaijan-specific required-documents page (sealed or direct-from-institution rules) is behind a login.

## Sources

[^1]: https://www.hcch.net/en/instruments/conventions/status-table/notifications/?csid=906&disp=type "The Federal Republic of Germany hereby withdraws its objection to the accession of the Republic of Azerbaijan to the Hague Convention of 5 October 1961"
[^2]: https://www.hcch.net/en/instruments/conventions/status-table/notifications/?csid=906&disp=type "Therefore, the Convention entered into force between Germany and Azerbaijan on 16 March 2026."
[^3]: https://www.hcch.net/en/instruments/conventions/status-table/notifications/?csid=906&disp=type "Since the objection was received after the time limit for filing objections had expired, it will have no legal consequences."
[^4]: https://www.hcch.net/en/instruments/conventions/status-table/notifications/?csid=906&disp=type "including documents certified in notarial order and state civil acts registration documents; and the Ministry of Foreign Affairs of the Republic of Azerbaijan for other documents."
[^5]: https://ambbaku.esteri.it/it/servizi-consolari-e-visti/servizi-per-il-cittadino-italiano/dichiarazioni-di-valore/ "i documenti devono essere tradotti in italiano (non in inglese) e legalizzati con Apostille dal Ministero della Giustizia"
[^6]: https://nic.gov.ru/en/proc/nic/legalize "Documents issued in member countries of the multilateral or bilateral agreements, which abolish the requirement of legalization of documents, are accepted without legalization."
[^7]: https://www.kimep.kz/prospective-students/kz/admission/nostrification/ "1993 жылғы 22 қаңтардағы Минск Конвенциясына сәйкес ТМД елдерінде алған (Грузияны қоспағанда) білімі туралы құжаттар апостильденбейді және заңдастырылмайды."
[^8]: https://www.uni-assist.de/en/how-to-apply/assemble-your-documents/translations/ "If your country issues your education certificates (additionally) in German or English, we do not need a translation"
[^9]: https://www.uni-assist.de/en/how-to-apply/assemble-your-documents/translations/ "a department of the issuing school or university authorised to issue such translations."
[^10]: https://www.uni-assist.de/tools/laenderhinweise/laenderdetails/country/az/ "Eine Übersetzung aus Aserbaidschan akzeptieren wir nur, wenn ein aserbaidschanischer Notar oder eine aserbaidschanische Notarin die Unterschrift und Identität des Übersetzers oder der"
[^11]: https://www.uni-assist.de/tools/laenderhinweise/laenderdetails/country/az/ "Bitte schicken Sie uns folgende Dokumente in der Originalsprache und in deutscher oder englischer Übersetzung."
[^12]: https://stipendiumhungaricum.hu/wp-content/uploads/2025/11/Application_Guide_for_the_Stipendium_Hungaricum_Programme_2026_27_final.pdf "We require an official, notarized translation of all your original application documents, which are not originally written in English, Hungarian or in the language of the selected study programme."
[^13]: https://turkiyeburslari.gov.tr/applysteps "For applications made online through the Türkiye Scholarships Application System (TBBS), all candidates must upload the following documents to the system:"
[^14]: https://tbbsweb.azureedge.net/tbbsweb/Page/TurkiyeScholarhips/NewStudentDirectory/NewStudentDirectory-en.png.pdf "Approved transcript indicating the courses, grades and general point average (GPA) and its Turkish translation certified by notary public or Turkish foreign missions."
[^15]: https://tbbsweb.azureedge.net/tbbsweb/Page/TurkiyeScholarhips/NewStudentDirectory/NewStudentDirectory-en.png.pdf "You must have your passport, diploma, transcript, and health report prepared and translated into Turkish by institutions/bodies accredited by the Turkish Embassy/ Consulate."
[^16]: https://denklik.yok.gov.tr/tr/page/663 "Üniversitelerimize Yüksek Lisans veya Doktora başvurusunda bulunacak yabancı uyruklu ilgililerin, Klinik Uygulaması olan sağlık alanları dışındaki programlar için denklik başvurusu yapmalarına gerek bulunmamaktadır."
[^17]: https://denklik.yok.gov.tr/tr/page/663 "Denkliği talep edilen diploma veya mezuniyet belgesinin Türkiye Cumhuriyeti noterleri ya da Türkiye Cumhuriyeti dış temsilcilikleri tarafından onaylanmış Türkçe tercümesi aslı,"
[^18]: https://nic.gov.ru/en/proc/nic/legalize "in the Russian Federation according to the civil legislation is carried out by a notary."
[^19]: https://rosnou.ru/en/entrant/Recognitionofforeigneducationandlegalizationofdocuments/ "notarized translation of official transcripts."
[^20]: https://rosnou.ru/en/entrant/Recognitionofforeigneducationandlegalizationofdocuments/ "Since 2019, the procedure for the recognition of foreign education (nostrification) has become mandatory for graduates of foreign educational organizations entering Russian universities."
[^21]: https://www.chevening.org/faqs/do-i-need-to-translate-my-university-transcripts-before-i-upload-them-to-the-application-form/ "No, Chevening does not require university transcripts to be translated."
[^22]: https://www.chevening.org/faqs/what-education-documents-do-i-need-to-upload/ "We require the original documents. They do not need to be translated into English."
[^23]: https://www.ox.ac.uk/admissions/graduate/application-guide/supporting-documents/official-transcript "Any translations of transcripts you upload to your application which are not accompanied by the original version will be rejected."
[^24]: https://www.ucl.ac.uk/study/prospective-students/graduate/how-apply/getting-your-academic-transcript "If your documents are not in English, you must also upload a full translation of each document – prepared by your institution or a registered translator."
[^25]: https://study.ed.ac.uk/postgraduate/applying/what/translations "a sworn translator (this would be a translator sworn before a court in a non-UK jurisdiction)"
[^26]: https://www.wes.org/resource-library/blog/credential-advice/translation-requirements-for-a-wes-credential-evaluation/ "For credential evaluations processed in the United States, WES requires translations of documents issued in languages other than English."
[^27]: https://www.wes.org/resource-library/blog/credential-advice/translation-requirements-for-a-wes-credential-evaluation/ "WES cannot accept English- or French-language versions of the documents in place of a translation."
[^28]: https://www.wes.org/resource-library/blog/credential-advice/translation-requirements-for-a-wes-credential-evaluation/ "All text in the original language must be accurately translated into English or French."
[^29]: https://az.usembassy.gov/fulbright-foreign-student-program/ "Academic transcripts/diplomas (certified translation into English or verified copies of original academic transcript and degree certificate – scanned and attached to the application);"
[^30]: https://az.usembassy.gov/fulbright-foreign-student-program/ "Nominated candidates will have to submit a copy of their original academic transcript bearing all official, notarized stamps to U.S. Embassy Baku."
[^31]: https://ciss.konkuk.ac.kr/bbs/ciss/4141/1205098/download.do "documents written in a language other than English or Korean must be submitted together with a certified translation"
[^32]: https://ciss.konkuk.ac.kr/bbs/ciss/4141/1205098/download.do "If the document is written in both languages (original language and English), it does not need to be translated again."
[^33]: https://www.mext.go.jp/content/20250413-mxt-kotokoku01-000041728_002.pdf "These documents must be written in Japanese or English, or if they are written in any other languages, a translation in either Japanese or English should be attached."
[^34]: https://ee.china-embassy.gov.cn/eng/dssghd/202511/t20251108_11749277.htm "Transcripts in languages other than Chinese or English must be attached with notarized Chinese or English translations."
[^35]: https://ambbaku.esteri.it/it/servizi-consolari-e-visti/servizi-per-il-cittadino-italiano/dichiarazioni-di-valore/ "In alternativa alla Dichiarazione di Valore, se consentito dalle Università, gli studenti possono ottenere, attraverso il sito web del CIMEA"
[^36]: https://miur.mur.gov.it/studiare-in-italia/studying/info-07.html "traduzione legale in italiano del titolo stesso."
[^37]: https://www.azerbaidjan.campusfrance.org/fr/etudes-en-france-procedure-de-candidature "des diplômes, annexes et relevés de notes obtenus au cours des trois dernières années d’études"
[^38]: https://www.netherlandsworldwide.nl/foreign-qualifications-netherlands/evaluation-study "If your diploma is not in Dutch, English, German or French, you need to get it translated by a sworn translator."
[^39]: https://welcome.uj.edu.pl/en_US/admission/documents/graduate "be translated by a sworn translator into Polish or English (depending on the language of the programme)."
[^40]: https://welcome.uj.edu.pl/en_US/admission/documents/graduate "A translation certified by a notary is not accepted."
[^41]: https://welcome.uj.edu.pl/en_US/admission/documents/graduate "If the document bears an apostille, it must also be translated."
[^42]: https://welcome.uj.edu.pl/en_US/admission/documents/graduate "be recognised by the Director of NAWA - this applies to documents issued outside the EU, OECD and EFTA, Ukraine and China xueshi"
[^43]: https://www.cvut.cz/en/assessment-of-education-for-applying-to-ctu "Documents must be officially translated into Czech or English by a Czech sworn translator."
[^44]: https://www.cvut.cz/en/assessment-of-education-for-applying-to-ctu "No translation is required for documents issued in English."
[^45]: https://www.kimep.kz/prospective-students/kz/admission/nostrification/ "II қадам: Қазақ /орыс тілдеріне аудару (егер құжаттар шетел тілінде болса) және Алматы қаласының нотариусында келесі құжаттарды нотариалдық куәландыру:"
[^46]: https://eqe.ge/en/page/static/213/utskhoetshi-mighebuli-ganatlebis-aghiareba "Any foreign language document is subject to the notarization of its translation into Georgian language!"
[^47]: https://eservices.moe.gov.ae/Equivalency/RequiredDocuments.aspx?Lang=en-US&Studylevel=2 "Certified translation of non-Arabic and English certificates."
[^48]: https://www.qu.edu.qa/en-us/students/admission/graduate/Pages/faq.aspx "Except for Arabic transcripts, We require all transcripts from higher learning (BA, BSc, MA, MSc for example) to be officially translated to English translation."
[^49]: https://master-economics-qem.eu/application-and-practical-information/how-apply "Documents must either be in English or be accompanied by an official certified English translation."
