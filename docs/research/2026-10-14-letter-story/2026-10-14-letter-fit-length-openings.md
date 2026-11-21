# Letter engine: programme fit without a named person, thin profiles and length, openings by culture

Date: 2026-10-14. This note adds to earlier work and does not repeat it: `docs/research/2026-09-28-letter-engine/admissions-readers.md`, `specificity.md`, `letter-rules.csv` (L-028 Göttingen/DAAD, L-055 Leiden, L-062, L-072/L-073 Cambridge booklet) and `~/agent-workspace/elmify-runs/motivation-letter/2026-10-12-human-admissions-writing-literature.md`. Findings that already live in those files (Göttingen's "do not retell", MIT's "echo that language", LSE's rankings/London clause, TUM's "generic letter is not sufficient", Oxford's over-length removal, Leiden's 10% over-length penalty, Cambridge's three failure modes) are only referred to here, not quoted again.

## Sub-questions

1. **Q1.** When no professor, lab or module can be verified, what do official pages tell applicants to write instead to answer "why this programme"?
2. **Q2a.** What should an applicant with a thin profile (a new bachelor's graduate with no work or research) write about?
3. **Q2b.** Is a letter that is clearly under the expected length penalised, or is "short and specific" preferred?
4. **Q3.** How should the first paragraph open in German, Russian, Turkish and French letters: a plain statement of the programme, or an anecdote or hook?

## Method and tools

- **How the candidate pages were found.** Exa searches in German, Russian, Turkish and French, each describing a university or career-service page about a master's motivation letter. Follow-up searches were limited to official domains: German universities, DAAD and uni-assist; Dutch universities; French universities, Onisep and Campus France. Brave was used for exact phrases and `site:` searches (Türkiye Bursları, Campus France, nes.ru, UK `ac.uk`).
- **How pages were read.** Every cited page was read with scrapling `get`/`bulk_get`, and every quote below is copied from that output.
- **Not used.** Tavily and Context7 were not used. Context7 does not apply to this question.
- **What failed.** PDFs came back as binary, which made them unreadable for quoting. RANEPA's blog and Türkiye Bursları' evaluation page came back as empty JavaScript shells. `arsiv.turkiyeburslari.gov.tr` did not resolve. Claims that rest only on those pages are marked **Unverified**.
- **Search ran out before Korean or Dutch-language pages were found.** That gap is listed under Open questions.

## Q1. "Why this programme" when nothing specific could be verified

**Answer.** Official pages agree on two things.

- **Readers do not want the university described back to them.** That rules out rankings, prestige, reputation, the city, or the programme page paraphrased.
- **The fallback is the applicant's own reason, tied to features the programme visibly has.** These are named courses and modules in general, a specialisation or track, the teaching approach, an internship or work-study structure (*alternance*), the skills it develops, where graduates go, and the link from those features to the applicant's past study and future plan.

The Göttingen-versus-MIT tension noted in earlier work is settled the same way by every page below. Name the feature, then give a reason that only this applicant has. The reason is what carries the paragraph, not the description.

**What official pages tell applicants not to write:**

- **France, Strasbourg.** The University of Strasbourg's maths and computing faculty gives a bad example, "Je souhaite venir à l'université de Strasbourg car elle est reconnue pour la qualité de son enseignement et la cathédrale est magnifique" (*I want to come to Strasbourg because it is known for its teaching and the cathedral is beautiful*).[^1] It labels it "motivations « passe-partout », non étayées par des faits précis" (*one-size-fits-all reasons, not backed by precise facts*).[^2]
- **France, Campus France.** Campus France's guidance gives "Je souhaite intégrer votre université car elle est prestigieuse." (*I want to join your university because it is prestigious*) as a sentence to avoid.[^3]
- **UK, Imperial.** "Try not to get too caught up with rankings or facts about the university".[^4] "We want to hear about you, not us!"[^5]
- **UK, Sussex.** Sussex's "Don't" example is "I was inspired by the University's world-renowned researchers and world-leading facilities."[^6]
- **Switzerland, Zurich (German-language).** The University of Zurich's career service, writing about job letters, says to avoid copying slogans from the reader's own website: "Vermeide: Standardsätze/Marketing- oder Werbeslogans von Webseiten des Arbeitgebers".[^7] This is job context, but it is the same rule as Göttingen's.

**What official pages offer as the substitute:**

- **France, Strasbourg.** The good example is "Je souhaite venir dans le master XXX car je suis particulièrement intéressé par les enseignements de XXX et de XXX pour les raisons suivantes" (*…because I am particularly interested in the courses X and Y for the following reasons*).[^8] The reasons are what the reader wants.
- **France, Onisep and Mon Master.** These are the French state's official advisers for the national master's platform. "Vous pouvez citer des enseignements pour montrer votre connaissance du parcours et expliquer en quoi ils complèteront votre formation antérieure et contribueront à la réalisation de votre projet professionnel." (*Cite courses to show you know the track, and explain how they complete your previous training and serve your career plan.*)[^9]
- **France, Lyon 3.** Lyon 3's master's page tells applicants to "développer ce qui vous intéresse dans cette formation" (*develop what interests you in this programme*).[^10] It lists the kinds of feature that count: the courses covered, the fact that the programme includes work-study, the target skills and the career outcomes. This is the clearest official licence to use **structure features** (internship or *alternance*, specialisation) when no person can be named.
- **France, Campus France.** Campus France lists concrete alternatives: certain courses, a specialisation, a teaching approach, a research area, a progression path, and the skills to be developed. It closes with "Montrez que vous avez pris le temps de vous renseigner sur la formation." (*Show you took the time to learn about the programme.*)[^11]
- **UK, Imperial.** "It's good to talk about the course content, but make sure that you relate it back to your experience and your goals".[^12]
- **Netherlands, Utrecht.** University College Utrecht's master's guidance wants a "description of the development of your interests and competences" that led to this master's.[^13] It also says: "Specify what you are applying for and say how you learned of the opportunity and why you are doing this one specifically."[^14]
- **Russia, HSE.** HSE's own online-campus guide says to show the link between goals and modules: "Покажите связь между вашими целями и учебными модулями." (*Show the link between your goals and the curriculum modules.*)[^15] It also says "Назовите дисциплины и лаборатории, которые для вас наиболее важны." (*Name the courses and labs that matter most to you.*)[^16]
- **Turkey, Özyeğin.** Özyeğin University's career office says the "why this programme/institution" question must be answered and that "Kurumla bağ kurulması kritik" (*building a link to the institution is critical*).[^17]

**Unverified (search snippets only; the PDFs could not be read):**

- Utrecht's USE master's motivation template asks "What distinguishes this programme from others you have considered?" and invites applicants to "refer to 1–2 similar programmes". Comparing against similar programmes is a fit device that needs no named person.
- An HSE department news page (inno.hse.ru) tells applicants to compare the programme "с реальными аналогами" (*with real alternatives*).

**What this means for the engine (inference).** When the verified-fact store has no named person, lab or module, the fit paragraph should be built from three things:

1. one programme feature that can be checked on the programme page (a track or specialisation, internship or work-study, thesis structure, a course area, or graduate outcomes);
2. the applicant's own prior course or project that this feature continues;
3. the applicant's plan that needs it.

The engine should never restate the programme page or name a ranking or the city. Where nothing can be checked, it can name the *kind* of thing the applicant wants to learn and why. Campus France explicitly accepts an unsettled plan: "Votre projet n'a pas besoin d'être parfaitement défini." (*Your plan does not need to be fully defined.*)[^18]

## Q2a. What applicants with thin profiles should write about

**Answer.** Official pages expect the following, and treat having no internship as normal:

- relevant courses (with good grades in them);
- a university project, thesis or long essay;
- voluntary or student activity;
- awards or scholarships;
- skills, shown through an example.

They want a few items connected to the programme, not a CV list. One HSE source warns that "I got top grades" is weaker than a concrete result.

- **France, Onisep and Mon Master.** To a student with no internship and no dissertation: "Vous pouvez en revanche mettre en avant d’autres éléments de votre parcours" (*you can instead highlight other parts of your background*), via the letter or the platform's "engagements" (activities) section.[^19] They also say "Les résultats universitaires ne sont qu’un des éléments étudiés dans votre candidature." (*Academic results are only one of the things assessed.*)[^20] And they encourage applicants to highlight "travaux universitaires, expériences professionnelles ou engagements bénévoles" (*university work, work experience or volunteering*) linked to the programme: "n’hésitez pas à souligner des projets en lien avec la formation".[^21]
- **France, Campus France.** The "parcours" (background) paragraph may draw on "les enseignements qui vous ont particulièrement intéressé" (*courses that particularly interested you*), a university project, an internship, an association, or a skill.[^22] Campus France also says "Ne répétez pas l'intégralité de votre CV." (*Do not repeat your whole CV.*)[^23]
- **UK, Imperial.** Imperial splits the evidence section into "your academic background, your work experience and skills and your other non-academic activities or interests".[^24]
- **UK, Sussex.** "mention relevant study - including projects, dissertations, essays - or work experience".[^25]
- **UK, Loughborough (grades).** Loughborough's assessment criteria list "Marks or grades achieved for individual subjects or modules taken, particularly where they provide an important foundation for further study at postgraduate level."[^26]
- **Netherlands, Utrecht (grades).** University College Utrecht: "Briefly list the relevant courses you have taken and their grades" (advice for the CV that goes with the letter).[^27]
- **Turkey, Boğaziçi.** Boğaziçi's career centre says applicants can mention "akademik geçmişinizdeki dersleri, dersini aldığınız tanınmış hocaları ve alanda ders dışı aktivitelerinizi belirtebilirsiniz" (*the courses in your academic background, the well-known lecturers you studied under, and your extracurricular activities in the field*).[^28] It also says "Hayatınız boyunca kazandığınız ödüller, burslar ya da elde ettiğiniz başarılardan ilgili olanlara mektubunuzda yer verebilirsiniz." (*You can include relevant awards, scholarships or achievements.*)[^29]
- **Turkey, METU.** METU's Informatics Institute: "Bu mektupta, başvurduğunuz programa yönelik olarak özgeçmişinizi özetleyiniz." (*In this letter, summarise your background as it relates to the programme.*)[^30] Also "Aldığınız ödül, burs vb. var ise bu konuda bilgi veriniz" (*if you have awards, scholarships etc., give details*).[^31]
- **Russia, HSE (a caution on grades).** "«Учился на отлично» менее убедительно, чем «создал прототип, привел 120 пользователей, представил решение на конференции»." (*"I was a straight-A student" is less convincing than "built a prototype, brought in 120 users, presented it at a conference".*)[^32] Read this together with Loughborough: grades in specific relevant courses count, a bare overall average does not.
- **Changing field.** Strasbourg's maths and computing faculty wants the reason for any change of direction or institution stated: "Dans votre lettre de motivation, si vous avez changé d'orientation ou d'établissement, indiquez la raison."[^33]

## Q2b. Length: is a short letter penalised, or is "short and specific" preferred?

**Answer.** Most official pages prefer short and dense over long and padded, usually with a soft ceiling of one page. Three things qualify that.

1. **A hard minimum can disqualify.** The one hard minimum found is the New Economic School in Moscow: letters under 400 words are not considered (**Unverified**, see below). Stipendium Hungaricum's "minimum 1 page" is already recorded as L-031. So where a minimum exists, falling short is a rejection, not a style issue.
2. **"Too short" is a recognised mistake.** Loughborough names "not providing enough information" as a common pitfall, while also saying the statement need not be long. Thin means missing content, not few words.
3. **A stated range is part of the test.** HSE treats keeping within a stated range as a test in its own right. Oxford and Leiden penalise going over (earlier work).

Nothing found says a letter is penalised for falling short of a *maximum* when no minimum is stated.

- **Netherlands, Utrecht.** "You should make it as short as possible while still hitting the important points."[^34] Also "short and sweet is important!"[^35]
- **France, Campus France.** "inutile de paraphraser pour faire une lettre un peu plus longue" (*no point padding to make the letter a bit longer*).[^36] Also "Une lettre de motivation ne doit jamais excéder la longueur d'une page" (*never more than one page*).[^37]
- **Germany, TU Dresden.** For the Deutschlandstipendium, a national merit scholarship: "Das Motivationsschreiben hat den Umfang einer DIN A4-Seite" (*one A4 page*)[^38] and "Formulieren Sie also knapp, präzise und mit hoher Informationsdichte." (*So write briefly, precisely and with a high density of information.*)[^39]
- **Switzerland, Zurich.** "Länge: maximal eine Seite" (*length: one page at most*). This is job context.[^40]
- **UK, Imperial.** "Make sure you are concise and that your points are clear and relevant."[^41]
- **UK, Loughborough (both sides).** "Your personal statement doesn't need to be long".[^42] It also lists "Not providing enough information" among common pitfalls[^43] and adds "Include everything that's relevant to your chosen programme and will make your application shine."[^44]
- **UK, Sussex.** A hard band: "be between 250 and 500 words".[^45]
- **Russia, HSE (a range as a test).** "Соблюдайте объем: если указано «от 400 до 1000 слов», уложитесь в этот диапазон." (*Keep to the length: if it says 400–1000 words, stay in that range.*)[^46] And "Это не просто правило хорошего тона, но проверка на умение выражаться кратко и ясно." (*It is not just good manners but a test of your ability to write briefly and clearly.*)[^47]
- **Turkey, Boğaziçi (typical length).** "Ortalamada 500-600 kelime arasında olan SoP" (*the statement of purpose, 500–600 words on average*).[^48]
- **Unverified: New Economic School (Moscow), MAF/MSF programmes.** Search snippets of the school's PDF (`https://admissions.nes.ru/master/documents/MAF,-MSF-Motivation-Letter-Requirements.pdf`) read "Объём мотивационного письма не менее 400 слов и не более 1000 слов" and "Письма объёмом менее 400 слов не будут рассматриваться приёмной комиссией" (*letters under 400 words will not be considered by the admissions committee*). The PDF was fetched but came back as binary, so the wording was not confirmed from the page.

**What this means for the engine (inference).**

- Treat a published minimum as a hard floor (`min_words`, as L-008 already argues for CSC).
- Treat a maximum as a ceiling. Do not pad toward it.
- With no stated length, aim for about one page.
- For a thin profile, a shorter letter that covers why this programme, what the applicant brings and their plan is consistent with every official source found. A letter that skips one of those three is the "not enough information" failure.

## Q3. How the first paragraph opens, by letter culture

**Answer.** In the continental sources (German, Russian, Turkish, French), the official structure is the same everywhere: a short, plain opening that says who the applicant is (current study or status) and what they are applying for, often with the main reason in one clause. Four points qualify that.

- **None of these official pages recommends an anecdote opening.** The Russian (HSE) and French (Campus France) pages explicitly want the opening short and immediately clear.
- **The bare formula is disliked too.** The plain statement should not be the "hiermit bewerbe ich mich" type (*I hereby apply…*): one German-language university career service names that formula as an empty opener (job context).
- **Several sources warn against a life story,** though not against an opening anecdote by name. No official source found explicitly bans an anecdote opening in these cultures.
- **UK sources differ.** Sussex and Loughborough explicitly want an "eye-catching" or "attention-grabbing" opening, and Sussex's model opening is a family-illness story. Imperial lists "I am applying for this course because…" as a cliché.

So the plain statement of the programme is the safe default for German, Russian, Turkish and French letters. A UK reader is the one reader who asks for a hook.

### German (Motivationsschreiben)

- **TU Dresden (scholarship letter).** The first move is a brief self-description, not a story: "Zunächst sollten Sie kurz Ihre Persönlichkeit beschreiben" (*first, briefly describe your personality*). After that comes the degree programme and why TU Dresden.[^49]
- **University of Zurich career service (job letters).** "Verzichte auf überflüssige Einleitungen wie «hiermit bewerbe ich mich…» oder «ich habe die Stelle auf Ihrer Webseite gefunden…»" (*leave out superfluous openings such as "I hereby apply…" or "I found the post on your website…"*).[^50]
- **uni-assist (earlier work, L-057).** uni-assist, the central application service many German universities use, requires the university and programme name in bold at the top. So the "what I am applying for" line can be a header and the first sentence can carry the reason.
- **Not cited.** Many commercial German guides say to avoid "hiermit bewerbe ich mich" and some suggest an anecdote or quote, which shows the advice is not uniform. They are commercial, so they are not cited.
- **Gap.** No German university page on *master's admission* openings was fetched. See Open questions.

### Russian (мотивационное письмо)

- **HSE.** "Вступление должно быть коротким и содержательным." (*The introduction should be short and substantive.*)[^51] Its listed elements are "Кто вы сейчас — профиль работы или должность." (*who you are now: field or position*)[^52] and "Куда и зачем подаете документы." (*where you are applying and why*)[^53] plus one main motive. The stated reason: "Такое начало экономит время приемной комиссии: сразу понятно, кто вы, чего хотите и соответствуют ли ваши цели программе обучения." (*Such an opening saves the committee time: it is immediately clear who you are, what you want and whether your goals match the programme.*)[^54]
- **HSE, against autobiography.** Its "mistakes" list rejects autobiography: "Напишите один абзац о том, кто вы, дальше — задачи, кейсы и планы." (*Write one paragraph on who you are, then goals, cases and plans.*)[^55]
- **Unverified: RANEPA.** The RANEPA blog (`ranepa.ru/blog/...kak-sostavit-motivatsionnoe-pismo...`) is described in a search index as saying "многие эксперты советуют" (*many experts advise*) an "эффектный тезис, занимательную историю из своей жизни, яркую цитату" (*a striking thesis, an entertaining story from your life, a vivid quote*) in the introduction. The page came back as an empty shell, so this is not confirmed. If accurate, it is a Russian university source that tolerates a hook, framed as other experts' advice rather than the admissions office's own rule.
- **Unverified: an HSE PDF template.** A search snippet of an HSE programme PDF (`admissions.hse.ru/mirror/pubs/share/532439902`) begins its template "Я, ………………, хочу принять участие в конкурсе кандидатов, поступающих на магистерскую программу" (*I, [name], wish to take part in the competition for the master's programme…*). That is the most formal conventional opening found.

### Turkish (niyet mektubu / motivasyon mektubu)

- **Özyeğin University career office.** Under "1. Giriş" (*introduction*): "Kısa ve net bir giriş yapılmalı" (*the introduction should be short and clear*)[^56] and "Hangi pozisyona/programa başvurduğun açıkça belirtilmeli" (*state clearly which position/programme you are applying for*).[^57]
- **METU.** METU frames the whole letter as a summary of background aimed at the programme.[^30]
- **Not used.** Commercial Turkish guides recommend an attention-grabbing hook paragraph; none is official.
- **Türkiye Bursları (government scholarship).** It scores "content/clarity of the letter of intent" (earlier work). No official opening advice from Türkiye Bursları was readable this session.

### French (lettre de motivation)

- **Campus France.** "Commencez par présenter clairement l'objet de votre candidature." (*Begin by stating clearly what you are applying for.*)[^58] It continues: "Votre introduction doit être courte et permettre au lecteur de comprendre immédiatement votre démarche." (*Your introduction should be short and let the reader understand your purpose immediately.*)[^59] Its first paragraph is "Votre situation" (*your situation*): who you are and which programme. This page is written for first-year undergraduate admission but labels the letter "(L2, Master, ...)".
- **Lyon 3, a master's programme page.** First part, "Se présenter" (*introduce yourself*): "Succinctement, vous devez décrire votre parcours" (*briefly describe your background*).[^60]
- **Campus France Madagascar.** For the "Études en France" online motivation field: "Cette courte lettre de motivation doit comprendre 3 éléments" (*this short letter must contain three elements*). It starts with academic background, then the target programme.[^61]
- **Unverified: Panthéon-Sorbonne geography department PDF.** It tells applicants to ban clichés such as "j'aime les animaux depuis mon enfance" (*I have loved animals since childhood*). The PDF text was seen in search output only.
- **Unverified: Grenoble career-service PDF.** It advises "Rédigez une bonne accroche" (*write a good hook*), in job context. So French career services do use the word *accroche*, but the official master's-application pages above put the programme statement first.

### Contrast reader: UK

- **Sussex.** The opening must "have an eye-catching and interesting introduction"[^62] and should not start with clichés. "Instead tell us what has influenced you to study this course."[^63] Its model opening is "It was not until my grandmother was diagnosed" (a personal story).[^64] Yet the same page says a statement "should not contain any autobiographical information about your personal life".[^65] The reconciliation is that a brief influence leading straight into the academic interest is accepted; a life story is not.
- **Loughborough.** "Your opening sentence should be bold and attention-grabbing."[^66]
- **Imperial.** Under "Avoid cliché and common phrases"[^67] it lists "I am applying for this course because"[^68] alongside "From a young age…". So the plain continental opening sentence reads as a cliché to at least one UK reader.

**What this means for the engine (inference).** Choose the opening by the destination's letter culture, not by the letter's language.

- **German, Russian, Turkish or French destination** (including English-language programmes in those countries): who I am now + what I apply for + one main reason, in 2–3 sentences, with no anecdote and no "hiermit bewerbe ich mich".
- **UK destination:** open with the specific influence or problem that led to the subject, at most one or two sentences, then go straight to academic evidence. This fits the earlier N-16 rule (origin slot is one paragraph, never the arc).
- **US faculty readers:** the earlier work (Caltech, MIT, Pavlo) already advises against childhood openings.

## Sources

[^1]: https://mathinfo.unistra.fr/admission/admission/conseils-pour-candidater "Je souhaite venir à l'université de Strasbourg car elle est reconnue pour la qualité de son enseignement et la cathédrale est magnifique."
[^2]: https://mathinfo.unistra.fr/admission/admission/conseils-pour-candidater "non étayées par des faits précis"
[^3]: https://www.bielorussie.campusfrance.org/fr/comment-rediger-une-lettre-de-motivation "Je souhaite intégrer votre université car elle est prestigieuse."
[^4]: https://www.imperial.ac.uk/study/apply/postgraduate-taught/application-process/personal-statement/ "Try not to get too caught up with rankings or facts about the university"
[^5]: https://www.imperial.ac.uk/study/apply/postgraduate-taught/application-process/personal-statement/ "We want to hear about you, not us!"
[^6]: https://www.sussex.ac.uk/study/masters/apply/tips-for-masters/personal-statement "I was inspired by the University's world-renowned researchers and world-leading facilities."
[^7]: https://www.careerservices.uzh.ch/de/ratgeber/bewerbung/bewerbungsdossier/Anschreiben.html "Standardsätze/Marketing- oder Werbeslogans von Webseiten des Arbeitgebers"
[^8]: https://mathinfo.unistra.fr/admission/admission/conseils-pour-candidater "je suis particulièrement intéressé par les enseignements de XXX et de XXX pour les raisons suivantes"
[^9]: https://www.onisep.fr/nos-tchats/revivez-nos-tchats/tchat-mon-master-bien-preparer-votre-phase-de-candidature "Vous pouvez citer des enseignements pour montrer votre connaissance du parcours"
[^10]: https://bourgenbresse.univ-lyon3.fr/comment-rediger-sa-lettre-de-motivation-pour-integrer-le-master-marketing-vente-de-liaelyon-sur-le-campus-de-bourg-en-bresse "Il est important dans cette partie de développer ce qui vous intéresse dans cette formation"
[^11]: https://www.bielorussie.campusfrance.org/fr/comment-rediger-une-lettre-de-motivation "Montrez que vous avez pris le temps de vous renseigner sur la formation."
[^12]: https://www.imperial.ac.uk/study/apply/postgraduate-taught/application-process/personal-statement/ "make sure that you relate it back to your experience and your goals"
[^13]: https://students.uu.nl/en/university-college-utrecht/student-life-and-career-orientation/masters/cv-and-motivation-letter "a description of the development of your interests and competences"
[^14]: https://students.uu.nl/en/university-college-utrecht/student-life-and-career-orientation/masters/cv-and-motivation-letter "Specify what you are applying for and say how you learned of the opportunity and why you are doing this one specifically."
[^15]: https://online.hse.ru/blog/statyi/privychka-uchitsja/zachem-nuzhno-motivacionnoe-pismo-i-kak-ego-sostavit "Покажите связь между вашими целями и учебными модулями."
[^16]: https://online.hse.ru/blog/statyi/privychka-uchitsja/zachem-nuzhno-motivacionnoe-pismo-i-kak-ego-sostavit "Назовите дисциплины и лаборатории, которые для вас наиболее важны."
[^17]: https://www.ozyegin.edu.tr/tr/profesyonel-gelisim/ogrenciler-icin/niyet-mektubu-nedir "Kurumla bağ kurulması kritik"
[^18]: https://www.bielorussie.campusfrance.org/fr/comment-rediger-une-lettre-de-motivation "Votre projet n'a pas besoin d'être parfaitement défini."
[^19]: https://www.onisep.fr/nos-tchats/revivez-nos-tchats/tchat-mon-master-bien-preparer-votre-phase-de-candidature "Vous pouvez en revanche mettre en avant d’autres éléments de votre parcours"
[^20]: https://www.onisep.fr/nos-tchats/revivez-nos-tchats/tchat-mon-master-bien-preparer-votre-phase-de-candidature "Les résultats universitaires ne sont qu’un des éléments étudiés dans votre candidature."
[^21]: https://www.onisep.fr/nos-tchats/revivez-nos-tchats/tchat-mon-master-bien-preparer-votre-phase-de-candidature "n’hésitez pas à souligner des projets en lien avec la formation"
[^22]: https://www.bielorussie.campusfrance.org/fr/comment-rediger-une-lettre-de-motivation "les enseignements qui vous ont particulièrement intéressé"
[^23]: https://www.bielorussie.campusfrance.org/fr/comment-rediger-une-lettre-de-motivation "Ne répétez pas l'intégralité de votre CV."
[^24]: https://www.imperial.ac.uk/study/apply/postgraduate-taught/application-process/personal-statement/ "your academic background, your work experience and skills and your other non-academic activities or interests"
[^25]: https://www.sussex.ac.uk/study/masters/apply/tips-for-masters/personal-statement "mention relevant study - including projects, dissertations, essays - or work experience"
[^26]: https://www.lboro.ac.uk/study/apply/masters-degree/ "Marks or grades achieved for individual subjects or modules taken, particularly where they provide an important foundation for further study at postgraduate level."
[^27]: https://students.uu.nl/en/university-college-utrecht/student-life-and-career-orientation/masters/cv-and-motivation-letter "Briefly list the relevant courses you have taken and their grades"
[^28]: https://kariyermerkezi.bogazici.edu.tr/tr/akademik-niyet-mektubu-statement-purpose-sop "akademik geçmişinizdeki dersleri, dersini aldığınız tanınmış hocaları ve alanda ders dışı aktivitelerinizi belirtebilirsiniz"
[^29]: https://kariyermerkezi.bogazici.edu.tr/tr/akademik-niyet-mektubu-statement-purpose-sop "Hayatınız boyunca kazandığınız ödüller, burslar ya da elde ettiğiniz başarılardan ilgili olanlara mektubunuzda yer verebilirsiniz."
[^30]: https://ii.metu.edu.tr/tr/basvuru-gereksinimleri "Bu mektupta, başvurduğunuz programa yönelik olarak özgeçmişinizi özetleyiniz."
[^31]: https://ii.metu.edu.tr/tr/basvuru-gereksinimleri "Aldığınız ödül, burs vb. var ise bu konuda bilgi veriniz"
[^32]: https://online.hse.ru/blog/statyi/privychka-uchitsja/zachem-nuzhno-motivacionnoe-pismo-i-kak-ego-sostavit "менее убедительно, чем «создал прототип, привел 120 пользователей, представил решение на конференции»"
[^33]: https://mathinfo.unistra.fr/admission/admission/conseils-pour-candidater "Dans votre lettre de motivation, si vous avez changé d'orientation ou d'établissement, indiquez la raison."
[^34]: https://students.uu.nl/en/university-college-utrecht/student-life-and-career-orientation/masters/cv-and-motivation-letter "You should make it as short as possible while still hitting the important points."
[^35]: https://students.uu.nl/en/university-college-utrecht/student-life-and-career-orientation/masters/cv-and-motivation-letter "short and sweet is important!"
[^36]: https://www.bielorussie.campusfrance.org/fr/comment-rediger-une-lettre-de-motivation "inutile de paraphraser pour faire une lettre un peu plus longue"
[^37]: https://www.bielorussie.campusfrance.org/fr/comment-rediger-une-lettre-de-motivation "Une lettre de motivation ne doit jamais excéder la longueur d'une page"
[^38]: https://tu-dresden.de/studium/rund-ums-studium/foerderung-und-finanzierung/deutschlandstipendium/bewerben/motivationsschreiben?set_language=de "Das Motivationsschreiben hat den Umfang einer DIN A4-Seite"
[^39]: https://tu-dresden.de/studium/rund-ums-studium/foerderung-und-finanzierung/deutschlandstipendium/bewerben/motivationsschreiben?set_language=de "Formulieren Sie also knapp, präzise und mit hoher Informationsdichte."
[^40]: https://www.careerservices.uzh.ch/de/ratgeber/bewerbung/bewerbungsdossier/Anschreiben.html "Länge: maximal eine Seite"
[^41]: https://www.imperial.ac.uk/study/apply/postgraduate-taught/application-process/personal-statement/ "Make sure you are concise and that your points are clear and relevant."
[^42]: https://www.lboro.ac.uk/study/apply/masters-degree/ "Your personal statement doesn't need to be long"
[^43]: https://www.lboro.ac.uk/study/apply/masters-degree/ "Not providing enough information"
[^44]: https://www.lboro.ac.uk/study/apply/masters-degree/ "Include everything that's relevant to your chosen programme and will make your application shine."
[^45]: https://www.sussex.ac.uk/study/masters/apply/tips-for-masters/personal-statement "be between 250 and 500 words"
[^46]: https://online.hse.ru/blog/statyi/privychka-uchitsja/zachem-nuzhno-motivacionnoe-pismo-i-kak-ego-sostavit "уложитесь в этот диапазон"
[^47]: https://online.hse.ru/blog/statyi/privychka-uchitsja/zachem-nuzhno-motivacionnoe-pismo-i-kak-ego-sostavit "Это не просто правило хорошего тона, но проверка на умение выражаться кратко и ясно."
[^48]: https://kariyermerkezi.bogazici.edu.tr/tr/akademik-niyet-mektubu-statement-purpose-sop "Ortalamada 500-600 kelime arasında olan SoP"
[^49]: https://tu-dresden.de/studium/rund-ums-studium/foerderung-und-finanzierung/deutschlandstipendium/bewerben/motivationsschreiben?set_language=de "Zunächst sollten Sie kurz Ihre Persönlichkeit beschreiben"
[^50]: https://www.careerservices.uzh.ch/de/ratgeber/bewerbung/bewerbungsdossier/Anschreiben.html "Verzichte auf überflüssige Einleitungen wie «hiermit bewerbe ich mich…»"
[^51]: https://online.hse.ru/blog/statyi/privychka-uchitsja/zachem-nuzhno-motivacionnoe-pismo-i-kak-ego-sostavit "Вступление должно быть коротким и содержательным."
[^52]: https://online.hse.ru/blog/statyi/privychka-uchitsja/zachem-nuzhno-motivacionnoe-pismo-i-kak-ego-sostavit "Кто вы сейчас — профиль работы или должность."
[^53]: https://online.hse.ru/blog/statyi/privychka-uchitsja/zachem-nuzhno-motivacionnoe-pismo-i-kak-ego-sostavit "Куда и зачем подаете документы."
[^54]: https://online.hse.ru/blog/statyi/privychka-uchitsja/zachem-nuzhno-motivacionnoe-pismo-i-kak-ego-sostavit "Такое начало экономит время приемной комиссии"
[^55]: https://online.hse.ru/blog/statyi/privychka-uchitsja/zachem-nuzhno-motivacionnoe-pismo-i-kak-ego-sostavit "Напишите один абзац о том, кто вы, дальше — задачи, кейсы и планы."
[^56]: https://www.ozyegin.edu.tr/tr/profesyonel-gelisim/ogrenciler-icin/niyet-mektubu-nedir "Kısa ve net bir giriş yapılmalı"
[^57]: https://www.ozyegin.edu.tr/tr/profesyonel-gelisim/ogrenciler-icin/niyet-mektubu-nedir "Hangi pozisyona/programa başvurduğun açıkça belirtilmeli"
[^58]: https://www.bielorussie.campusfrance.org/fr/comment-rediger-une-lettre-de-motivation "Commencez par présenter clairement l'objet de votre candidature."
[^59]: https://www.bielorussie.campusfrance.org/fr/comment-rediger-une-lettre-de-motivation "Votre introduction doit être courte et permettre au lecteur de comprendre immédiatement votre démarche."
[^60]: https://bourgenbresse.univ-lyon3.fr/comment-rediger-sa-lettre-de-motivation-pour-integrer-le-master-marketing-vente-de-liaelyon-sur-le-campus-de-bourg-en-bresse "Succinctement, vous devez décrire votre parcours"
[^61]: https://www.madagascar.campusfrance.org/conseils "Cette courte lettre de motivation doit comprendre 3 éléments"
[^62]: https://www.sussex.ac.uk/study/masters/apply/tips-for-masters/personal-statement "have an eye-catching and interesting introduction"
[^63]: https://www.sussex.ac.uk/study/masters/apply/tips-for-masters/personal-statement "Instead tell us what has influenced you to study this course."
[^64]: https://www.sussex.ac.uk/study/masters/apply/tips-for-masters/personal-statement "It was not until my grandmother was diagnosed"
[^65]: https://www.sussex.ac.uk/study/masters/apply/tips-for-masters/personal-statement "should not contain any autobiographical information about your personal life"
[^66]: https://www.lboro.ac.uk/study/apply/masters-degree/ "Your opening sentence should be bold and attention-grabbing."
[^67]: https://www.imperial.ac.uk/study/apply/postgraduate-taught/application-process/personal-statement/ "Avoid cliché and common phrases"
[^68]: https://www.imperial.ac.uk/study/apply/postgraduate-taught/application-process/personal-statement/ "I am applying for this course because"

## Open questions

- **Q1. No Korean source and no Dutch-language source.** GKS or Korean university guidance on "why this programme" without a named professor was not searched. Its absence is a gap, not a finding. The Utrecht USE "compare with 1–2 similar programmes" template and UvA's "which Research Master's courses" form are PDFs whose wording is **Unverified**.
- **Q2. One hard minimum that rejects short letters, still Unverified.** The New Economic School's 400-word floor rests on a PDF that could not be read as text. Stipendium Hungaricum's "minimum 1 page" (L-031) remains the verified example from earlier work. No source was found on how a letter well under a *maximum* (with no minimum) is scored.
- **Q3, German.** No German university page on how to open a *master's admission* Motivationsschreiben was fetched. The German evidence is a scholarship page (TU Dresden) and a Swiss job-letter page (Zurich). Next step: German university Studienberatung pages, or the DAAD sheet already in L-028.
- **Q3, Russian.** RANEPA's apparent tolerance of a hook ("занимательную историю из своей жизни", *an entertaining story from your life*) is **Unverified**, because the page is a JavaScript shell. HSE's formal "Я, …, хочу принять участие в конкурсе" (*I, …, wish to take part in the competition*) template is **Unverified** (PDF).
- **Q3, Turkish.** No Türkiye Bursları guidance on openings was readable: the main site is a JavaScript shell and the archive host did not resolve. The Turkish evidence comes from university career offices (Özyeğin, Boğaziçi) and METU's application page.
- **Q3 overall.** No official source in these four cultures *explicitly* forbids an anecdote opening. The finding is that every official structure found starts with a statement of who the applicant is and what they apply for, and two (HSE, Campus France) say the opening must make that clear immediately.
- **Source caveats.**
  - The Campus France Belarus page targets first-year undergraduate admission while naming the master's level in its form.
  - The Zurich and some Grenoble material is about job letters.
  - The Özyeğin page contains an apparent typo ("Kuruma özel yazılmaması", literally *should not be written for the institution*, followed by "(genel mektup kullanma)", *do not use a generic letter*), so its tip list should not be quoted on tailoring.
