# CV engine gaps: CV language, military service, names, CV vs form consistency

Researched 2026-10-13, inline.
Seven quotes come from PDFs the automatic citation check cannot read: [^1], [^3], [^4], [^6], [^7],
[^16] and [^22]. Each was confirmed word for word with `pdftotext` on 2026-10-13. The Fulbright PDF ([^17])
refused automated download (403); its quote was read from a search extract and is **Unverified**. The `researcher` agent was not available in this session.
Scope: master's applicants, first students from Azerbaijan. Primary sources only. Each claim
has a link and a short verbatim quote. Where an official source was looked for and not found,
it says NOT FOUND.

## 1. Which language the CV must be in

**Answer: it varies by programme, not by country.** Some French- and German-taught
programmes require the CV in the language of instruction. Others accept French or English,
or German or English. So the CV language is a per-programme rule read from the page, the
same way as `cv_scope`, and the engine needs a translated CV for some programmes.

| Source | Rule |
|---|---|
| German Sport University Cologne | CV in the language of instruction[^1] |
| masterib (German master's) | German or English[^2] |
| Campus France Turkey, Études en France master's guide | CV in French[^3]; English documents only for English-taught programmes[^4] |
| Université Toulouse – Jean Jaurès (master's) | CV in French[^5] |
| Eiffel scholarship (Campus France) | French or English, two pages max[^6] |
| Mon Master (France) | One general CV; some programmes allow a second CV, specific or in English[^7] |
| TU Hamburg | CV asked only for English-taught master's[^8] |

Not checked this time: Türkiye, Netherlands, Switzerland, Italy, Hungary, Korea, Japan, China,
UK, US and Erasmus Mundus. The pattern above (programme-level rule) is the decision input.

Two more findings from the same pages:
- **A signed CV.** Hochschule Kempten asks for "Lebenslauf (CV) mit Unterschrift"[^9]. The
  catalog's R-031 recorded no funder requiring a signature on the CV. This programme does, so the
  signature line needs to be a per-programme rule too.
- **A tabular CV.** "Tabellarischer Lebenslauf" is asked for explicitly[^9] (already in S-008).

## 2. Compulsory military service

**Azerbaijan, from the law itself** ("Hərbi vəzifə və hərbi xidmət haqqında", e-qanun.az):
- **Length:** 1 year for those with higher education, 1 year 6 months otherwise[^10].
- **Deferral:** full-time bachelor's, master's and doctoral students are deferred until they
  finish, including when studying abroad[^11]. Deferred conscripts are called up until age 35[^12].
- **So for our applicants:** a man applying straight from his bachelor's to a full-time master's
  abroad is usually deferred, and his CV has no service period. A man who served after his
  bachelor's has a gap of about 12 months to account for.

**How to show it on an admissions CV: NOT FOUND in any official admissions or university
careers guide.** Searched: university careers services (UK, US, Australia), UCAS, admissions
FAQs. UCAS says disclosing service is optional, and that "It won't reflect negatively on your
application"[^13]. That is UK Armed Forces veterans, not conscription.

**Recommendation (inference, not sourced):** treat it like the catalog's gap entries (S-041,
S-045): one line with dates and no detail, for example "Compulsory military service, Armed Forces
of the Republic of Azerbaijan, Oct 2024 – Oct 2025". Where a programme requires a gap-free CV
(`no_gaps`, `cv_scope` complete: ETH, TUM, uni-assist), the entry is required. Elsewhere it is
still printed, because an unexplained 12-month gap is worse than one line.

## 3. Which spelling of the student's name

- **Azerbaijani passports carry both spellings.** "Azerbaijan passports show the holder's names,
  in Azeri and English"[^14].
- **In the English spelling, Ə becomes A.** A report on transliteration in Azerbaijani identity
  documents: "“ə” hərfi ingilis dilinə tərcümə zamanı yalnız “a” hərfi ilə əvəzlənir" ("ə" is
  replaced only by "a" in the English rendering)[^15]. **Unverified:** the Academy of Sciences
  page now redirects to its home page; the quote was read from a search extract. The GOV.UK line
  above and Azerbaijani English spellings in practice (Mammadov, Aliyev) agree with it. So Məmmədov is MAMMADOV.
- **ICAO's international passport rule** lets national Latin letters appear in the printed zone
  ("Diacritics are permitted. Latin-based national characters")[^16]. Its transliteration table has no entry for Ə, so the issuing
  state decides; as above, Azerbaijan uses A.
- **Application platforms take the passport spelling.**
  - Fulbright: "Enter your name exactly as it appears on your passport"[^17] (**Unverified**: read from a search extract).
  - US SEVIS name standards (used by every US graduate school for the I-20): "Nonimmigrant names
    entered in SEVIS should match the name in the passport's MRZ"[^18].
  - A Norwegian university's checklist: "Any name change must be documented"[^19].

**Recommendation:** the CV prints the passport's English spelling (MAMMADOV-style), so it
matches the application form. A diploma or transcript translation that spells the name another
way is flagged to the counsellor. A transliteration difference needs no legal proof; a real
name change does. The engine never re-spells a name itself. Nothing found says the native
spelling may not appear alongside, but nothing asks for it either. Default: passport spelling only.

## 4. Leaving items off the CV while the form lists everything

- **Declarations cover the application and the academic record, not a selective CV.**
  - UBC (graduate): "I confirm that I have disclosed all non-UBC post-secondary academic history
    information"[^20].
  - Auckland: "no information that would have a bearing on my admission or enrolment has been
    withheld"[^21].
  - University of Michigan: "Falsification or omission of information and credentials may result
    in the withdrawal of my application"[^22].
  - UC Davis GSM names "Omission of required information" as an integrity breach[^23].
- **A CV is expected to be selective.** University of Birmingham (postgraduate taught): "You can
  upload your CV and detail any relevant work experience that may be beneficial to your
  application"[^24].
- **Calling an irrelevant award left off a CV "omission" or "misrepresentation": NOT FOUND**
  in any declaration read.

**Recommendation:** the relevance engine may leave optional items off the CV. It must never
leave out:
1. anything in the academic record (education, which is already never dropped);
2. anything a programme requires (`cv_scope` complete, `no_gaps`);
3. anything the same application's form also asks for in a CV-checked field.

The CV and the form must never contradict each other on dates, titles or grades. That is a
consistency check, not a completeness one.

## Open questions

- The CV language rule for the destinations not checked here.
- Whether admissions readers mind a native-spelling line beside the passport spelling. No source found.
- How portals that parse an uploaded CV react to a translated CV. Not researched.

[^1]: https://www.dshs-koeln.de/web/shared/dokumente/studienunterlagen/master/application-guidelines/Non-EU-application-guideline-master-WS26-27.pdf "always in the language of instruction"
[^2]: https://www.masterib.de/bewerbung/05_Bewerbungsunterlagen/index.html "Die Bewerbungsunterlagen können in deutscher oder in englischer Sprache eingereicht werden"
[^3]: https://www.turquie.campusfrance.org/system/files/medias/documents/2022-12/Proc%C3%A9dure%20de%20candidature%20master.pdf "(Le CV doit être rédigé en français)"
[^4]: https://www.turquie.campusfrance.org/system/files/medias/documents/2022-12/Proc%C3%A9dure%20de%20candidature%20master.pdf "Les documents en anglais ne seront acceptés que si vous avez postulé dans des programmes dont l’anglais est la langue d’enseignement"
[^5]: https://www.univ-tlse2.fr/accueil/etudiant-etranger/venir-ut2j/demande-dadmission-en-master "une lettre de motivation et un curriculum vitae (CV) rédigés en français"
[^6]: https://www.mexique.campusfrance.org/system/files/medias/documents/2024-10/guide_depot_candidatures_eiffel_2025.pdf "rédigé en français ou en anglais, sur deux pages"
[^7]: https://information.monmaster.gouv.fr/documents/5/Guide_du_candidat_-_phase_candidature-pourCMS_compressed.pdf "Certaines formations vous donnent la possibilité de déposer un second"
[^8]: https://www.tuhh.de/tuhh/studium/vor-dem-studium/bewerbung/masterstudiengaenge-deutschsprachig "Lebenslauf (nur für die englischsprachigen Masterstudiengänge)"
[^9]: https://www.hs-kempten.de/studium/bewerbung/master/unterlagen "Lebenslauf (CV) mit Unterschrift"
[^10]: https://frameworks.e-qanun.az/23/c_f_23021.html "hərbi qulluqçuları: ali təhsili olanlar"
[^11]: https://frameworks.e-qanun.az/23/c_f_23021.html "əyani təhsilalma formasında bakalavriatda, magistraturada, doktoranturada"
[^12]: https://frameworks.e-qanun.az/23/c_f_23021.html "35 yaşına çatanadək müddətli həqiqi hərbi xidmətə çağırılırlar"
[^13]: https://www.ucas.com/search/frequently-asked-questions/applying-to-study-%E2%80%93-veterans "It won't reflect negatively on your application"
[^14]: https://www.gov.uk/government/publications/azerbaijan-knowledge-base-profile/azerbaijan-knowledge-base-profile "Azerbaijan passports show the holder’s names, in Azeri and English"
[^15]: https://science.gov.az/az/news/open/20534 "ingilis dilinə tərcümə zamanı yalnız"
[^16]: https://www.icao.int/sites/default/files/publications/DocSeries/9303_p3_cons_en.pdf "Diacritics are permitted. Latin-based national characters"
[^17]: https://dz.usembassy.gov/wp-content/uploads/sites/226/2026/04/2027-FFSP-Application-Instructions.pdf "Enter your name exactly as it appears on your passport"
[^18]: https://studyinthestates.dhs.gov/sevis-help-hub/sevis-basics/system-data-entry-standards/name-standards "should match the name in the passport"
[^19]: https://www.usn.no/english/academics/how-to-apply/for-non-eu-eea-applicants/ "Any name change must be documented"
[^20]: https://okanagan.calendar.ubc.ca/admissions/ubc-graduate-admissions-student-declaration "I confirm that I have disclosed all non-UBC post-secondary academic history information"
[^21]: https://www.auckland.ac.nz/en/study/applications-and-admissions/how-to-apply/applicant-declaration.html "no information that would have a bearing on my admission or enrolment has been withheld"
[^22]: https://lsa.umich.edu/content/dam/weinberginstitute-assets/admissions-add-degree-cert.pdf "Falsification or omission of information and credentials may result in the withdrawal of my application"
[^23]: https://gsm.ucdavis.edu/graduate-degrees/mba/sacramento-part-time-mba/admissions/statement-application-integrity "Omission of required information"
[^24]: https://www.birmingham.ac.uk/study/postgraduate/taught/apply/your-application "detail any relevant work experience that may be beneficial to your application"
