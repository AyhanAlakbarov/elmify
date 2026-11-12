# CV word lists (six languages) and how many "general merit" items a master's CV keeps

Date: 2026-10-12. Scope: two questions for the admissions CV engine.

## Result in five lines

1. **Soft-skill word lists:** native, checkable sources exist for EN, FR, TR, RU and (thinner) DE; for Azerbaijani only one ministry-newspaper page, one state-university news page and two commercial pages were found. Lists are in section 2.
2. **Thesis words:** one native source per language for the main term; several secondary terms (Diplomarbeit, mémoire de master, магистерская диссертация, diplom işi, Capstone) could only be seen in PDFs or page titles and are marked **Unverified**.
3. **"Action verb first" must not be applied to German or Turkish.** KIT's career service says action verbs are the *English* convention "statt im Nominalstil"; Karadeniz Technical University's own sample CV prints verbless verbal-noun lines. **French** guidance asks for action verbs but in the infinitive, and forbids full sentences. **Russian is the opposite of the brief's assumption:** every Russian career-centre source found asks for verbs (perfective, past tense), not nouns.
4. **Merit items:** NOT FOUND — no official source gives a number cap for awards, extracurriculars, volunteering or certificates on a master's CV. New numbers found are for neighbours only (max 4 hobbies, max 3–4 publications, up to 3 references).
5. **New recency and relevance rules** were found (Oxford "recent achievements" / "only … relevant"; University of Florida "from the date you completed high school"; Pace "at least the past five years"). They conflict with ETH/TUM "leave nothing out" already in S-047, so the rule stays per destination.

## 1. Sub-questions answered

- Q1a. Which soft-skill terms does a native careers or employment-service source list, per language?
- Q1b. Which word names a thesis in each language, per a native source?
- Q1c. Does native guidance for DE, FR, RU, TR prescribe noun-first (verbless) lines or verbs?
- Q2a. Does any official admissions or careers source give a **number** for awards / extracurricular / volunteering / certificates?
- Q2b. Does any give a **recency** cutoff or a **relevance** filter not already in the catalog?

### How the candidate sources were found

Candidates came from searches, not memory: Exa (`web_search_exa`, and `web_search_advanced_exa` restricted to `francetravail.fr`, `edu.tr`, `edu.az`/`gov.az`, a list of Russian and German university domains), then Brave (`"Soft Skills" Teamfähigkeit Belastbarkeit Lebenslauf site:arbeitsagentur.de`). Every footnoted page was then fetched live with scrapling `get` and the quote copied from that output.

### Tools and limits in this session

- No shell: `git show origin/master:…` could not be run. The catalog rows were read from the working-tree copies of `docs/research/cv-style-rules.csv` and `cv-rules.csv` (branch `claude/extraction-cause-and-humanizer-note`), which may differ from `origin/master`.
- scrapling `get` returns binary for PDFs, so PDFs cannot be quoted through it. Four PDFs were read with `tavily_extract` instead; nothing from a PDF carries a footnote, and every PDF-only claim is marked **Unverified (PDF)**.
- Context7 was not used (not a library question). Europass/ESCO translated terminology was not fetched: the ESCO portal is a script-rendered app and S-050 already records that the Europass editor could not be read.

## 2. Q1a — soft-skill terms

Reading the tables: **Verified** = the term was read on a live HTML page fetched in this run (footnote = a sentence from that page). **Unverified** = seen only in a PDF, a search-engine extract, or an unreachable page.

A finding that matters for the filler rule, in three languages: the sources that list these words also call them empty when listed bare. The German federal employment agency says soft skills need not be in the CV at all.[^5] HSE calls «Ответственный, коммуникабельный» clichés.[^31] The Azerbaijani education ministry's newspaper says naming them "is not enough".[^33]

### English

Sources: UK National Careers Service (defines the category)[^1][^2]; Loughborough University Student Services (longest list, headed "skills employers seek", does not use the word "soft").[^3][^4]

| Status | Terms |
|---|---|
| Verified, National Careers Service | communication, leadership, time management, conflict management, problem solving, mentoring, positivity, flexibility, team player |
| Verified, Loughborough | analytical ability, commercial awareness, communication, creativity, decision making, emotional intelligence, entrepreneurial, flexibility, influencing, initiative, interpersonal, leadership, negotiating, networking, organisation, people management, planning, presentation, problem solving, resilience, self-awareness, self-confidence, self-development, self-management, self-motivation, teamwork, time-management |
| Unverified (search extract only: UCAS, Prospects, Wolverhampton) | adaptability, attention to detail, critical thinking, reliability, self-discipline, work ethic, independence |

Spelling variants to match (derived, not separately sourced): `teamwork / team work / team-work / team player`, `time management / time-management`, `problem solving / problem-solving`, `organisation / organization / organisational skills`, `interpersonal (skills)`, `communication (skills)`.

### German

Sources: Bundesagentur für Arbeit, ZAV newsletter (names three and says to leave them out of the CV)[^5]; BA Jobbörse help (calls "persönliche Stärken" the so-called soft skills and lets a user pick five, giving Belastbarkeit and Teamfähigkeit as examples)[^6]; Universität Rostock Careers Service (competencies tested in assessment centres — a competency list, not a CV-skills list)[^7][^8][^9][^10]; Leuphana Career Service[^11]; KIT Career Service.[^12]

| Status | Terms |
|---|---|
| Verified, BA | Teamfähigkeit, Belastbarkeit, Kundenorientiertheit |
| Verified, Rostock | Stressresistenz, Kommunikationsfähigkeit, Teamfähigkeit, analytisches Denken, soziale Kompetenz, Durchsetzungsfähigkeit, Kompromissbereitschaft, Kooperationsbereitschaft, Durchsetzungsvermögen, Entscheidungsfreudigkeit, Organisationsfähigkeit, Selbstdarstellung, Kreativität, Rhetorik, Überzeugungskraft; adjectives `belastbar`, `motiviert` |
| Verified, Leuphana / KIT | soziale Kompetenzen, Teamfähigkeit, Kommunikationsstärke, unternehmerisches Denken |
| Unverified (BA brochures are PDFs; `ideenwerkstatt.arbeitsagentur.de` did not resolve) | Lernbereitschaft, Optimismus, Eigenmotivation, Veränderungsbereitschaft, Konfliktfähigkeit, Einfühlungsvermögen, Emotionale Intelligenz, Organisationstalent, Ganzheitliches Denken, Kundenorientierung, Durchhaltevermögen, Genauigkeit, Sorgfalt, Flexibilität, Eigeninitiative, Leistungsbereitschaft, Entscheidungsfähigkeit, Führungsfähigkeit, Zuverlässigkeit, Verantwortungsbewusstsein, Selbstständigkeit, interkulturelle Kompetenz, Disziplin; adjectives teamfähig, flexibel, kommunikativ, kontaktfreudig, zuverlässig, engagiert, zielstrebig, gewissenhaft |

The German verified list is 22 terms, below the 25 asked for. The BA's own complete "Stärken" catalogue sits behind the Jobbörse login; the help page describes its four groups but does not print the items.

Variants (derived): noun/adjective pairs `Teamfähigkeit / teamfähig / Teamgeist`, `Belastbarkeit / belastbar`, `Zuverlässigkeit / zuverlässig`, `Flexibilität / flexibel`; compounds `-fähigkeit`, `-bereitschaft`, `-stärke`, `-vermögen`, `-kompetenz`.

### French

Sources: France Travail (national employment service) — its list of 16 "savoir-être professionnels" for candidates[^13], its 14-item reference list[^14], and its soft-skills page.[^15][^16]

| Status | Terms |
|---|---|
| Verified, 14-item list | capacité d'adaptation, gestion du stress, travail en équipe, capacité à fédérer, sens de la communication, autonomie, sens de l'organisation, rigueur, force de proposition, curiosité, persévérance, prise de recul, réactivité, capacité de décision |
| Verified, 16-item list (verb form) | être à l'écoute, faire preuve de curiosité, faire preuve de leadership, faire preuve de réactivité, organiser son travail selon les priorités, travailler en équipe, faire preuve d'autonomie, s'adapter aux changements, prendre des initiatives, être force de proposition, gérer son stress, faire preuve de persévérance, faire preuve de rigueur et de précision, avoir le sens du service, respecter ses engagements, faire preuve de créativité |
| Verified, soft-skills page | résilience, aisance relationnelle, optimisme, confiance en soi, organisation, créativité, écoute active, communication orale, respect, sens du collectif, responsabilité, intégrité, attitude positive, intelligence émotionnelle, empathie, gestion du temps, audace, motivation, fiabilité, esprit d'équipe, patience, proactivité, leadership, esprit d'initiative, résolution de problèmes, sens de l'observation, sens des responsabilités, esprit de synthèse |
| Unverified (commercial or PDF) | polyvalence, dynamisme, sens du relationnel, esprit d'analyse, sens de l'écoute; adjectives dynamique, motivé(e), rigoureux/rigoureuse, autonome, curieux/curieuse, polyvalent(e) |

Variants (derived): `sens de l'…` / `sens du …` / `sens des …`, `capacité à/de …`, `esprit de/d'…`, `gestion du/des …`; both apostrophes (`'` and `’`) occur on the source pages.

### Turkish

Sources: Sakarya Üniversitesi career office (defines "yumuşak beceriler")[^17][^18]; Yeditepe Üniversitesi lifelong-learning centre[^19][^20][^21]; Karadeniz Teknik Üniversitesi career centre (a list of phrases recruiters are tired of — reported from a US survey, so partly translated)[^24][^25]; kariyer.net, a commercial job board, for long-form variants.[^22][^23]

| Status | Terms |
|---|---|
| Verified, Sakarya | iletişim, problem çözme, ekip çalışması, kişisel sorumluluk, mesleki etik, analitik düşünme, yaratıcı düşünme, dayanıklılık, esneklik, çeviklik, merak, yaşam boyu öğrenme, empati, aktif dinleme, öz farkındalık, motivasyon, liderlik, sosyal etki, hizmet odaklılık, uyum sağlama |
| Verified, Yeditepe | takım çalışması, etkili iletişim, çatışma yönetimi, eleştirel düşünme, karmaşık problem çözme, karar verme, zaman yönetimi, öz disiplin; named as clichés: takım oyuncusu, iletişimi kuvvetli, dinamik |
| Verified, KTÜ (tired phrases) | takım oyuncusu, sonuç odaklı, dinamik, motivasyonu yüksek, detay odaklı, proaktif, çok çalışan, stratejik düşünen, yardımsever |
| Verified, kariyer.net (commercial) | takım çalışmasına yatkınlık, ikna yeteneği, yaratıcılık, analiz yeteneği, organizasyon yeteneği, yönetim becerisi, stres yönetimi, zaman yönetimi, dakik olma, sorumluluk alabilme, detaylara önem verme |
| Unverified (İstanbul Kent Üniversitesi page fetched, single-word list items below the quote minimum; Afyon Kocatepe PDF) | sorumluluk bilinci, öğrenmeye açıklık, uyum sağlama becerisi, karar verme yetkinliği, adaptasyon becerileri, planlama ve organizasyon becerileri, dürüstlük |

Variants: `takım çalışması` and `ekip çalışması` are both attested for "teamwork". Suffixed forms seen on the pages: `… becerisi / becerileri`, `… yeteneği`, `… yönetimi`, `… odaklı`, `-ebilme` (e.g. `sorumluluk alabilme`).

### Russian

Sources: Tomsk Polytechnic University competence centre[^26] and State University of Management[^27] (the same eleven competencies, from the presidential "Россия — страна возможностей" assessment); hh.ru, the dominant commercial job board[^28][^29][^30]; HSE.[^31][^32]

| Status | Terms |
|---|---|
| Verified, TPU / GUU | партнерство и сотрудничество, планирование и организация, ориентация на результат, анализ информации и выработка решений, клиентоориентированность, следование правилам и процедурам, коммуникативная грамотность, саморазвитие, лидерство, стрессоустойчивость, эмоциональный интеллект |
| Verified, hh.ru (commercial) | коммуникабельность, лидерские качества, умение работать в команде, способность работать в команде, адаптивность, гибкость, ответственность, организованность, умение принимать решения, навыки коммуникации, способность решать проблемы, аналитический склад ума, креативность, самомотивация, внимание к деталям, аналитическое мышление, командная работа, эмпатия, терпение; named as clichés: «работаю на результат», «имею лидерские качества» |
| Verified, HSE | ответственный, коммуникабельный (called clichés); аналитический склад ума, целеустремленность, стремление развиваться |
| Unverified (KFU career centre unreachable; MISIS and NES are PDFs) | стрессоустойчивый, быстро обучаемый, обучаемость, устойчивость к неопределенности, умение работать в режиме многозадачности, критическое мышление |

Category names seen: `мягкие навыки`, `гибкие навыки`, `надпрофессиональные компетенции`, `софт-скилы`, `soft skills`, `личные качества`. Variants (derived): adjective/noun pairs `коммуникабельный / коммуникабельность`, `ответственный / ответственность`, `стрессоустойчивый / стрессоустойчивость`; feminine endings `-ая`.

### Azerbaijani

What was found, exactly. Searches restricted to `edu.az` and `gov.az` and to ADA, BSU, UNEC, ASOIU, BHOS, UFAZ and `dma.gov.az` returned **no page from ADA University, Baku State University or UNEC that lists soft skills**. BSU has only a news item about a CV workshop. The State Employment Agency (DMA) publishes an interview-preparation guide as a PDF and runs seminars at universities; its CV builder is behind a login. Checkable pages:

- "Azərbaycan müəllimi" (the Science and Education Ministry's newspaper), quoting an HR specialist.[^33]
- Mingəçevir State University, news of a DMA-led CV seminar.[^34]
- eduonline.az and cluvon.com — commercial portals; the second appears machine-translated across 40 languages, so treat its wording as weak evidence.[^35][^36][^37]

| Status | Terms |
|---|---|
| Verified, muallim.edu.az | liderlik bacarığı, məsuliyyətli (as `məsuliyyətliyəm`), komandada işləmək (as `komandada yaxşı işləyirəm`), özünü təqdimetmə bacarıqları |
| Verified, mdu.edu.az | analitik düşüncə, ünsiyyət bacarıqları, qərarvermə bacarıqları |
| Verified, eduonline.az (commercial) | komanda işi, kommunikasiya, problem həll etmə, vaxtın idarə olunması, ünsiyyət, təşkilatçılıq, məsuliyyət; named as generic: məsuliyyətli, çalışqan, pozitiv |
| Verified, cluvon.com (commercial, likely translated) | komanda ilə işləmək, ünsiyyət bacarığı, təşkilatçılıq, vaxtın idarə olunması, problem həlli, liderlik, məsuliyyətlilik, adaptasiya, empatiya, səbir |
| Unverified (PDF, search extract, or unfetched page) | komanda ilə işləmə bacarığı, ünsiyyət və kommunikasiya bacarıqları, problem həll etmə bacarığı, vaxt idarəetməsi, vaxtı idarə etmək, komandada işləmək bacarığı, stres menecmenti, tənqidi düşüncə, yumşaq bacarıqlar (category name, DMA PDF), punktual, diqqətli, öyrənməyə açıq |

The Azerbaijani verified list is about 22 distinct terms and rests on thin sources. Variants (derived): `komanda ilə / komandada işləmə(k) (bacarığı)`, `komanda işi`; `ünsiyyət bacarığı / bacarıqları`; `vaxtın idarə olunması / edilməsi`, `vaxt idarəetməsi`; `məsuliyyət / məsuliyyətli / məsuliyyətlilik`.

## 3. Q1b — thesis words

| Language | Term | Status and source |
|---|---|---|
| EN | thesis, dissertation | Verified, Wesleyan University career centre[^38] |
| EN | senior thesis, master's thesis, honors thesis | Verified, same page[^39] |
| EN | Bachelor's thesis, Capstone | **Unverified** — "Capstone Project" seen only in a Harvard sample-CV PDF via search extract |
| DE | Abschlussarbeit | Verified, Leuphana Career Service[^40] |
| DE | Masterarbeit | Verified, KIT Career Service[^41] |
| DE | Masterand (a role title: thesis written inside a company, printed as an experience entry) | Verified, KIT sample entry[^42] |
| DE | Bachelorarbeit, Masterarbeit (regulation use) | Verified, KIT economics faculty[^43] |
| DE | Examensarbeit | Seen on the Rostock page as a three-word list item, below the quote minimum |
| DE | Diplomarbeit | **Unverified** — only in the `<title>` of the KIT faculty page |
| FR | projet de fin d'études (PFE) | Verified, École nationale des ponts et chaussées[^45] |
| FR | mémoire | Verified, same page[^46] and Sciences Po Toulouse careers service[^47] |
| FR | mémoire de master, mémoire de fin d'études, thèse | **Unverified** — seen only in PDFs (a real academic CV, an ENPC department note) |
| TR | bitirme tezi | Verified, Yalova Üniversitesi engineering faculty directive[^48] |
| TR | yüksek lisans tezi | Verified, Ankara Üniversitesi[^49] |
| TR | bitirme projesi, bitirme çalışması, bitirme ödevi, lisans bitirme tezi, doktora tezi | **Unverified (PDF)** — Sakarya Üniversitesi directive lists the first four as names for one course |
| RU | выпускная квалификационная работа (ВКР) | Verified, HSE study handbook[^50] |
| RU | магистерская диссертация, дипломная работа, курсовая работа | **Unverified (PDF)** — SPbU and HSE regulations; the MSU journalism page that mentions курсовая работа returned empty |
| AZ | magistrlik dissertasiyası | Verified, Science and Education Ministry regulation[^51] |
| AZ | buraxılış işi | Verified, ministry rules for the bachelor level[^52] |
| AZ | diplom işi, kurs işi, dissertasiya işi | **Unverified** |

Two things the word list alone will get wrong:

- The official Azerbaijani term is **magistrlik dissertasiyası**, not "magistr dissertasiyası" as in the brief. Match both.
- In German a thesis done at a company is a real experience entry with a job-like title (`Masterand`, and by the same pattern `Bachelorand`, `Diplomand` — the last two not seen in a source). A rule that moves every thesis out of Experience would misfile these.

## 4. Q1c — noun-first or verb-first?

| Language | What native guidance says | Is noun-first the norm? |
|---|---|---|
| German | KIT, on English-language CVs: describe activities with action verbs "statt im Nominalstil" — the nominal style is the German default the student is told to leave behind.[^53] KIT's own German sample entries are nouns.[^54] The federal employment agency asks for "Stichpunkte" (keyword points), 3 to 5 per station.[^55] | **Yes.** Do not apply the verb-first rule. |
| French | Sciences Po Toulouse: no full sentences.[^56] France Travail: express a skill "avec un verbe d'action", and its examples are infinitives.[^57] Rennes 2: use "des verbes et des mots symbolisant l'action".[^58] Noun lines ("Gestion des stocks…") appear in a Paris-Saclay guide, a PDF. | **Mixed.** Verbs are recommended, but as infinitives; nouns are accepted. A rule expecting a past-tense verb first is wrong here. |
| Russian | hh.ru's corrected examples all start with a past-tense verb.[^59] Two university career guides say it outright — NES: use perfective verbs; MISIS: describe experience with verbs, not nouns — both PDFs, **Unverified (PDF)**. | **No.** Guidance prescribes verbs. Noun lines are common in practice but no source found endorses them. |
| Turkish | KTÜ: write in first or third person singular.[^60] Its own sample CV prints verbless verbal-noun lines.[^61] Yeditepe instead asks for "active verbs" such as yaptım, yönettim.[^62] Either way the verb or verbal noun comes **last** in the line. | **Verb-first is impossible** in Turkish word order. Verbal-noun lines are modelled by a university career centre; finite verbs are also recommended. |

## 5. Q2 — how many merit items, how far back, how relevant

### Number

**NOT FOUND** for awards, extracurricular activities, volunteering or certificates: no admissions office, scholarship body or university careers service found states a count. Searches for "at most five awards", "maximum number of extracurricular activities" and similar returned page limits per section (Quebec FRQ: awards and distinctions, maximum one page — a PDF, **Unverified**) but no item counts.

Numbers that were found, for neighbouring sections:

| Section | Number | Source and audience |
|---|---|---|
| Interests / hobbies | maximum four points | Leuphana Career Service, job applications[^70] |
| Publications | maximum 3–4 in the CV itself | KIT Career Service, doctoral candidates applying to industry[^71] |
| References | up to three | Wesleyan career centre, academic CV[^76] |
| References | usually two | KTÜ career centre[^78] |
| Skills | not 15–20 | eduonline.az, commercial, student CVs[^82] |
| Bullets per station | 3 to 5 | Bundesagentur für Arbeit[^55] (S-026 already has "5–6 at most") |

### Recency (new)

- **Oxford graduate admissions:** a required CV should "provide a summary of your recent achievements".[^63] Same page as S-009, which recorded only the length.
- **University of Florida, Materials Science graduate admissions (binding for that programme):** activities from the date high school was completed[^66]; education history from high school onward.[^67] This puts the line at the end of secondary school — pre-university achievements are out, the school itself is in.
- **Pace University graduate admission:** at least the past five years.[^68]
- **KIT:** school education is no longer given from the master's level on (stated for English-language CVs).[^72]
- **Bundesagentur für Arbeit:** the last or highest qualification is enough[^75]; the highest language certificate is enough.[^73]
- **Unverified (PDF):** Carnegie Mellon's graduate résumé guide says to select awards that are "timely (i.e. will not include high school honors)"; France's national Mon Master applicant guide says the CV may detail the path "depuis le bac".

### Relevance (new)

- **Oxford:** applicants "should only include material relevant to your application".[^64] And a page is often enough at master's level.[^65]
- **Yale School of the Environment, master's admissions:** only "significant" volunteer experience.[^69]
- **Wesleyan:** awards are listed in full; only the most noteworthy get an explanation.[^77] This is a rule about detail, not a filter on which awards appear.
- **Bundesagentur für Arbeit:** certificates only where relevant to the post.[^74]
- **Rennes 2:** only information pertinent to the selection process.[^80] **France Travail:** only the skills that reflect you best.[^81]
- **KTÜ:** do not list activities just to have listed them.[^79] **eduonline.az (commercial):** not every certificate.[^83] **HSE:** do not list courses and minors in the education block.[^84]

### How this sits with the catalog

Sources disagree, and the disagreement is by destination, which is what S-047 already concluded. ETH Zurich and TUM ("leaving nothing out", from upper-secondary or elementary school) and Harvard GSD (list everything, hobbies included) own the rule for their own admissions. Oxford owns the opposite rule for its own. No general careers page overrides either. A single "keep N merit items" constant has no source; a per-destination default of "university-era items only, relevant ones first, nothing from before the end of secondary school" has three (Oxford, Florida, KIT) and one PDF (CMU).

## Sources

[^1]: https://nationalcareers.service.gov.uk/careers-advice/how-to-develop-your-soft-skills "Soft skills are sometimes called transferable skills or employability skills by employers."
[^2]: https://nationalcareers.service.gov.uk/careers-advice/how-to-develop-your-soft-skills "Employers look for problem solving skills because it shows you can find problems and fix them."
[^3]: https://www.lboro.ac.uk/services/student-services/topics/skills-employers-seek/ "Below is a selection of the skills that employers are looking for in graduates"
[^4]: https://www.lboro.ac.uk/services/student-services/topics/skills-employers-seek/ "The ability to work with others in an organised manner to achieve a goal."
[^5]: https://www.arbeitsagentur.de/vor-ort/zav/working-and-living-in-germany/newsletter-iss/01-2026/bewerbung "Soft Skills wie Teamfähigkeit, Belastbarkeit oder Kundenorientiertheit müssen Sie in einem Lebenslauf nicht aufführen und können eher in Ihrem Anschreiben genannt werden."
[^6]: https://jobboerse.arbeitsagentur.de/vamJB/hilfe/de/AS/betreut/4.html "Sie können in diesem Bereich 5 Stärken wie"
[^7]: https://www.uni-rostock.de/studium/berufseinstieg/careers-service/portalseite-careers-service/info-wiki/rund-um-die-bewerbung/ "Geprüft wird hierbei die Kompromiss- und Kooperationsbereitschaft sowie das Durchsetzungsvermögen."
[^8]: https://www.uni-rostock.de/studium/berufseinstieg/careers-service/portalseite-careers-service/info-wiki/rund-um-die-bewerbung/ "Geprüft werden hierbei das Arbeiten unter Zeitdruck, die Entscheidungsfreudigkeit, die Organisationsfähigkeit und das analytische Denken."
[^9]: https://www.uni-rostock.de/studium/berufseinstieg/careers-service/portalseite-careers-service/info-wiki/rund-um-die-bewerbung/ "Besonderen Wert wird hier auf die Teamfähigkeit, die Selbstdarstellung und die Kreativität gelegt."
[^10]: https://www.uni-rostock.de/studium/berufseinstieg/careers-service/portalseite-careers-service/info-wiki/rund-um-die-bewerbung/ "Ich bin belastbar (Warum?)"
[^11]: https://www.leuphana.de/services/career-service/bewerben/die-schriftliche-bewerbung/der-lebenslauf.html "Wenn Sie eine Teamsportart betreiben, dann unterstreichen Sie damit Ihre Teamfähigkeit."
[^12]: https://www.careerservice.kit.edu/de/studierende/bewerbungssupport/bewerbungstipps/lebenslauf/ "Wichtige Kompetenzen sind neben Fachwissen unter anderem Projektmanagement, Kommunikationsstärke und unternehmerisches Denken"
[^13]: https://www.francetravail.fr/candidat/vos-recherches/preparer-votre-candidature/accompagne-dans-sa-recherche/les-3-types-de-competences-a-v-1.html "dans une liste de 16 items dont vous pouvez vous inspirer"
[^14]: https://www.francetravail.fr/candidat/vos-recherches/preparer-votre-candidature/accompagne-dans-sa-recherche/mettez-toutes-les-chances-de-vot.html "capacité d’adaptation, gestion du stress, travail en équipe, capacité à fédérer, sens de la communication"
[^15]: https://www.francetravail.fr/candidat/vos-recherches/bien-vous-organiser/quest-ce-que-le-savoir-etre.html "Les soft skills réunissent des traits de caractère (comme la résilience ou l’aisance relationnelle)"
[^16]: https://www.francetravail.fr/candidat/vos-recherches/bien-vous-organiser/quest-ce-que-le-savoir-etre.html "l’écoute active, la communication orale, le respect, le sens du collectif, la responsabilité, l’intégrité"
[^17]: https://kariyer.sakarya.edu.tr/tr/icerik/21821/145361/21-yuzyil-becerileri "Yumuşak beceriler ise iletişim, problem çözme, ekip çalışması, kişisel sorumluluk ve mesleki etik gibi bireyler arası ilişkileri ve kişisel özellikleri kapsayan"
[^18]: https://kariyer.sakarya.edu.tr/tr/icerik/21821/145361/21-yuzyil-becerileri "Empati, aktif dinleme, öz farkındalık ve motivasyon"
[^19]: https://yasamboyu.yeditepe.edu.tr/soft-skill-ve-hard-skill-cvde-nasil-yazilir-blog "Takım çalışması, empati, etkili iletişim ve çatışma yönetimi yetenekleri."
[^20]: https://yasamboyu.yeditepe.edu.tr/soft-skill-ve-hard-skill-cvde-nasil-yazilir-blog "Eleştirel düşünme, karmaşık problem çözme ve karar verme süreçlerini yönetme kabiliyeti."
[^21]: https://yasamboyu.yeditepe.edu.tr/soft-skill-ve-hard-skill-cvde-nasil-yazilir-blog "gibi herkesin yazdığı ancak içi doldurulmayan kelimelerden kaçının"
[^22]: https://www.kariyer.net/kariyer-rehberi/kisisel-becerilerinizi-ozgecmisinize-dahil-etme-yollari/ "Karşılıklı anlayış ve dostça ilişkiler geliştirebilme"
[^23]: https://www.kariyer.net/kariyer-rehberi/kisisel-becerilerinizi-ozgecmisinize-dahil-etme-yollari/ "Stres yönetiminde başarılı olma"
[^24]: https://www.ktu.edu.tr/kariyer/cvhazirlamateknikleri "Araştırmaya katılan İK profesyonelleri görmekten sıkıldıkları ifadeleri şöyle sıralıyor:"
[^25]: https://www.ktu.edu.tr/kariyer/cvhazirlamateknikleri "Takım oyuncusu ( Yüzde 15)"
[^26]: https://base.tpu.ru/competence/rsv/ "мягкие навыки - это навыки межличностной адаптируемости к различным людям, проблемам и ситуациям"
[^27]: https://science.guu.ru/student/softskills/ "Какие компетенции оценивают у студентов?"
[^28]: https://hh.ru/article/lichnye-kachestva-v-rezyume-kak-pravilno-podcherknut-svoi-silnye-storony "Софт-скилы, такие как коммуникабельность, лидерские качества и способность работать в команде, становятся всё более значимыми для работодателей в различных отраслях."
[^29]: https://hh.ru/article/lichnye-kachestva-v-rezyume-kak-pravilno-podcherknut-svoi-silnye-storony "Клише и банальные фразы, такие как «работаю на результат» или «имею лидерские качества»"
[^30]: https://hh.ru/article/lichnye-kachestva-v-rezyume-kak-pravilno-podcherknut-svoi-silnye-storony "«Я коммуникабельный, ответственный и умею решать проблемы»"
[^31]: https://online.hse.ru/blog/statyi/karernyj-lift/kak-sostavit-rezyume "«Ответственный, коммуникабельный» — сами по себе это клише, которые ничего не говорят о вас."
[^32]: https://gsb.hse.ru/careercentre/career/instruments "Моими сильными качествами можно назвать аналитический склад ума, целеустремленность и стремление развиваться."
[^33]: https://muallim.edu.az/ozunuz-haqqinda-danisin-asan-sualin-cetin-cavabi "“Liderlik bacarığım var”, “məsuliyyətliyəm”, “komandada yaxşı işləyirəm” demək kifayət deyil."
[^34]: https://mdu.edu.az/ru/cv-resume-seminar-14-05-26/ "tələbələrin analitik düşüncə, ünsiyyət və qərarvermə bacarıqlarının inkişafına"
[^35]: https://eduonline.az/universitet-telebesi-ucun-cv-nece-hazirlanmalidir-2026-ci-il-ucun-tam-beledci "ünsiyyət, komanda işi, təşkilatçılıq və məsuliyyət"
[^36]: https://eduonline.az/universitet-telebesi-ucun-cv-nece-hazirlanmalidir-2026-ci-il-ucun-tam-beledci "“məsuliyyətli, çalışqan, pozitiv” kimi ümumi ifadələrlə kifayətlənməyin."
[^37]: https://cluvon.com/az/cv-de-konullu-tecrubesini-teqdim-etmek "Səbir, məsuliyyət və insanlarla işləmək bacarığımı inkişaf etdirdim."
[^38]: https://careercenter.wesleyan.edu/resources/curriculum-vitae-cv-guide/ "Include your thesis or dissertation title under the degree it belongs to, especially if it demonstrates expertise relevant to the position."
[^39]: https://careercenter.wesleyan.edu/resources/curriculum-vitae-cv-guide/ "include the title of your senior or master’s thesis"
[^40]: https://www.leuphana.de/services/career-service/bewerben/die-schriftliche-bewerbung/der-lebenslauf.html "Fügen Sie ggf. Noten und den Titel von Abschlussarbeiten hinzu."
[^41]: https://www.careerservice.kit.edu/de/studierende/bewerbungssupport/bewerbungstipps/lebenslauf/ "zum Beispiel Thema der Masterarbeit, Vertiefungsfächer, Schwerpunkte, ausnahmsweise auch Seminare"
[^42]: https://www.careerservice.kit.edu/de/studierende/bewerbungssupport/bewerbungstipps/lebenslauf/ "Masterand im Bereich QRS"
[^43]: https://www.wiwi.kit.edu/anmeldungAbschlussarbeit.php "Für alle WiWi Masterarbeiten gilt eine Bearbeitungszeit von 6 Monaten ab offiziellem Anmeldetermin"
[^45]: https://ecoledesponts.fr/formation-initiale/formation-dingenieur/insertion-professionnelle/les-stages-et-le-projet-de-fin-detudes "Le projet de fin d'études (PFE) est la dernière étape de la formation"
[^46]: https://ecoledesponts.fr/formation-initiale/formation-dingenieur/insertion-professionnelle/les-stages-et-le-projet-de-fin-detudes "Il se termine par la rédaction d’un mémoire écrit"
[^47]: https://avenirpro.sciencespo-toulouse.fr/fr/article/comment-rediger-son-cv/29/10/2019/66 "grand thèmes abordés, travaux réalisés (mémoire, etc.)"
[^48]: https://muhendislik.yalova.edu.tr/tr/Icerik/Detay/bitirme-tezi-5 "Bitirme Tezi: Öğrencilerin lisans öğretimi kapsamında yapmaları gereken mezuniyet çalışmasını"
[^49]: https://egitim.ankara.edu.tr/yuksek-lisans-tezi-sureci/ "Yüksek Lisans Tezi Süreci"
[^50]: https://www.hse.ru/studyspravka/vkr "Выпускная квалификационная работа (ВКР)"
[^51]: https://edu.gov.az/az/esasnameler_353/783 "Magistrlik dissertasiyasının hazırlanması, təqdim olunması və müdafiəsi qaydaları haqqında əsasnamə"
[^52]: https://edu.gov.az/az/azerbaycan-respublikasi-tehsil-nazirliyinin-qebul-etdiyi-aktlar_374/1338 "Ali məktəbin bakalavr pilləsində buraxılış işlərinin hazırlanması qaydaları"
[^53]: https://www.careerservice.kit.edu/de/studierende/bewerbungssupport/bewerbungstipps/lebenslauf/ "Beschreibe deinen Tätigkeiten sehr spezifisch mit Action Verbs statt im Nominalstil."
[^54]: https://www.careerservice.kit.edu/de/studierende/bewerbungssupport/bewerbungstipps/lebenslauf/ "Entwicklung von Werkstoffen für XYZ"
[^55]: https://www.arbeitsagentur.de/bildung/bewerbung/lebenslauf "Füge den Arbeitgeber, deine Position und deine konkreten Aufgaben in wenigen kurzen Stichpunkten (3 bis 5 pro Station) hinzu."
[^56]: https://avenirpro.sciencespo-toulouse.fr/fr/article/comment-rediger-son-cv/29/10/2019/66 "Ne rédigez pas de phrases complètes"
[^57]: https://www.francetravail.fr/candidat/vos-recherches/preparer-votre-candidature/accompagne-dans-sa-recherche/les-3-types-de-competences-a-v-1.html "Vous pouvez exprimer ces compétences avec un verbe d’action"
[^58]: https://appui.univ-rennes2.fr/nos-modules/je-prepare-mon-insertion-professionnelle/m04-comprendre-2-le-reseau-professionnel/ "des verbes et des mots symbolisant l’action"
[^59]: https://hh.ru/article/lichnye-kachestva-v-rezyume-kak-pravilno-podcherknut-svoi-silnye-storony "«Возглавлял команду из 10 человек, обеспечивая выполнение проекта в срок и в рамках бюджета»"
[^60]: https://www.ktu.edu.tr/kariyer/cvhazirlamateknikleri "Birinci ya da üçüncü tekil kişi ağzıyla yazın."
[^61]: https://www.ktu.edu.tr/kariyer/cvhazirlamateknikleri "Pazarlama biriminin yeniden yapılandırılması"
[^62]: https://yasamboyu.yeditepe.edu.tr/soft-skill-ve-hard-skill-cvde-nasil-yazilir-blog "gibi kelimeler yetkinliklerinizin arkasındaki aksiyonu gösterir"
[^63]: https://www.ox.ac.uk/admissions/graduate/application-guide/supporting-documents/cv-resume "Where a separate CV is required, it should be one or two pages in length and provide a summary of your recent achievements."
[^64]: https://www.ox.ac.uk/admissions/graduate/application-guide/supporting-documents/cv-resume "should only include material relevant to your application"
[^65]: https://www.ox.ac.uk/admissions/graduate/application-guide/supporting-documents/cv-resume "A page is often enough, especially at master’s level."
[^66]: https://mse.ufl.edu/admissions/prospective-grad-students/step-by-step-guide-to-applying-for-the-graduate-program/ "Include all activities from the date you completed high school through the start date of the term for which you are applying."
[^67]: https://mse.ufl.edu/admissions/prospective-grad-students/step-by-step-guide-to-applying-for-the-graduate-program/ "Education history from high school/secondary school through the start month of the term for which you are applying"
[^68]: https://www.applyweb.com/pace/g_instruct.html "describing at least the past five years of your employment history and significant"
[^69]: https://environment.yale.edu/admissions/masters/application-materials-list "Include dates of service, employers, titles, nature of duties, and any significant volunteer experience."
[^70]: https://www.leuphana.de/services/career-service/bewerben/die-schriftliche-bewerbung/der-lebenslauf.html "Nennen Sie hier maximal vier Punkte, die möglichst vielseitig Ihre Interessen abbilden."
[^71]: https://www.careerservice.kit.edu/de/studierende/bewerbungssupport/bewerbungstipps/lebenslauf/ "Du kannst maximal 3-4 Publikationen direkt im Lebenslauf nennen."
[^72]: https://www.careerservice.kit.edu/de/studierende/bewerbungssupport/bewerbungstipps/lebenslauf/ "Deine Schulausbildung wird ab dem Master nicht mehr angegeben."
[^73]: https://www.arbeitsagentur.de/vor-ort/zav/working-and-living-in-germany/newsletter-iss/01-2026/bewerbung "wobei es genügt, das höchste Sprachzertifikat zu nennen"
[^74]: https://www.arbeitsagentur.de/vor-ort/zav/working-and-living-in-germany/newsletter-iss/01-2026/bewerbung "sofern diese für die ausgeschriebene Stelle relevant sind"
[^75]: https://www.arbeitsagentur.de/vor-ort/zav/working-and-living-in-germany/newsletter-iss/01-2026/bewerbung "hier ist es ausreichend, den letzten beziehungsweise höchsten Berufs- oder Bildungsabschluss zu nennen"
[^76]: https://careercenter.wesleyan.edu/resources/curriculum-vitae-cv-guide/ "List up to three references"
[^77]: https://careercenter.wesleyan.edu/resources/curriculum-vitae-cv-guide/ "Include enough information for the reader to understand the significance of the most noteworthy ones."
[^78]: https://www.ktu.edu.tr/kariyer/cvhazirlamateknikleri "Genellikle iki referans yazılır."
[^79]: https://www.ktu.edu.tr/kariyer/cvhazirlamateknikleri "Fazla ilgi duymadığınız aktiviteleri sırf yazmış olmak için yazmamalısınız."
[^80]: https://appui.univ-rennes2.fr/nos-modules/je-prepare-mon-insertion-professionnelle/m04-comprendre-2-le-reseau-professionnel/ "Seules y figurent les informations pertinentes pour le processus de recrutement."
[^81]: https://www.francetravail.fr/candidat/vos-recherches/bien-vous-organiser/quest-ce-que-le-savoir-etre.html "Pour ne pas surcharger votre CV, ne mettez que les compétences qui vous reflètent le mieux et vous mettent en valeur pour le poste auquel vous prétendez."
[^82]: https://eduonline.az/universitet-telebesi-ucun-cv-nece-hazirlanmalidir-2026-ci-il-ucun-tam-beledci "CV-yə 15–20 bacarıq yazmaq lazım deyil."
[^83]: https://eduonline.az/universitet-telebesi-ucun-cv-nece-hazirlanmalidir-2026-ci-il-ucun-tam-beledci "İştirak etdiyiniz bütün sertifikatları CV-yə əlavə etmək lazım deyil."
[^84]: https://gsb.hse.ru/careercentre/career/instruments "Не рекомендуем указывать курсы, майноры и пр. в этом блоке."

### PDF leads (read with tavily_extract or seen in search extracts; not machine-checked, no footnote)

- NES (РЭШ) CV guide, `guru.nes.ru/documents/cv-guide-nes2023.pdf` — perfective verbs; soft-skill examples (устойчивость к неопределенности, умение работать в команде, способность принимать решения).
- MISIS career centre guide, `misis.ru/files/-/8e53ab351df5efa086faebd7297753e1/mtd_25.pdf` — "глаголами, а не существительными"; avoid коммуникабельный, ответственный, стрессоустойчивый.
- Ankara Üniversitesi open course slides, `acikders.ankara.edu.tr/…/13. Etkili Mesleki İletişim ve Kariyer Planlaması.pdf` — third person singular, with verbal-noun examples.
- Carnegie Mellon graduate résumé guide, `cmu.edu/career/documents/sample-resumes-cover-letters/graduate_student_resume_guide_24.pdf` — no high-school honors.
- DMA (Azerbaijan State Employment Agency) interview guide, `dma.gov.az/storage/Msahib-y-haz-rl-q-texnikalar.pdf` — "yumşaq bacarıqlar", "analitik düşüncə və komandada effektiv işləmək bacarığı".
- Bundesagentur für Arbeit brochures (`arbeitsagentur.de/vor-ort/datei/bewerbungstipps_ba211652.pdf` and siblings) — the twelve-item soft-skill example list.
- TU Dresden Career Service annotated sample CV — noun-style bullets; Masterarbeit / Bachelorarbeit as labelled lines under the degree.
- Mon Master applicant guide (`information.monmaster.gouv.fr`) — CV may detail the path "depuis le bac".

## Open questions

1. **German soft-skill list is short (22 verified).** The BA's full "Stärken" catalogue is behind the Jobbörse login. A person with an account can copy it in five minutes; that would be the authoritative German list.
2. **Azerbaijani has no university-careers or employment-agency page listing soft skills in HTML.** The DMA PDF and its seminar slides are the likeliest primary source; someone should read the PDF in full, or ask DMA's Mərkəzi Karyera filialı for its CV handout.
3. **Russian noun-first lines:** guidance says verbs, practice is often nouns. Whether to *flag* noun lines in a Russian CV or merely not require verbs is a product decision; no source settles it.
4. **Secondary thesis terms** (Diplomarbeit, mémoire de master, mémoire de fin d'études, магистерская диссертация, дипломная работа, diplom işi, kurs işi, Capstone, Bachelor's thesis) are unverified in HTML. All are ordinary words a fluent reader would accept; they need one confirming page each, not research.
5. **No count for merit items exists in any source found.** If the engine needs a number, it is a house choice and should be recorded as one.
6. **Catalog rows were read from the working tree, not `origin/master`.** If master's rows S-009 … S-047 differ, the "new vs already recorded" calls in section 5 should be re-checked.
7. Europass/ESCO translated skill terminology was not checked.
