# Report: what makes a motivation letter read as the applicant's own (2026-09-28)

Tiers: PR = peer-reviewed, PP = preprint, OFF = official guidance/legal record, PRAC = practitioner, FOLK = folklore.

## 0. Two things to say before the six points
- Correction to the brief. Isley et al. do NOT report that AI essays scored lower on voice, commitment or leadership. They found AI essays got large gains in grammar, style and clarity and smaller gains on substance. The penalty (-1.5 pp admission per AI essay) survives controlling for measured quality, and officers marked down essays they *believed* were AI (coefficient -0.109) regardless of quality. So the cost is suspicion, not weaker content. https://arxiv.org/html/2609.22549 (PP)
- Several funders forbid AI-written text outright, so a human-sounding letter does not solve a declaration problem. Chevening: generating answers with AI is "strictly prohibited", applicants sign that they did not, and Chevening screens for it (OFF, https://www.chevening.org/faqs/can-i-use-ai-to-help-me-write-my-application/). UCAS: generating "all or a large part" "could be considered cheating"; brainstorming, structure and readability checks are allowed (OFF, Aug 2025, https://www.ucas.com/applying/applying-to-university/writing-your-personal-statement/a-guide-to-using-ai-and-chatgpt-with-your-personal-statement). A German court upheld TUM excluding a master's applicant over a ChatGPT essay (OFF, VG München M 3 E 23.4371, 28.11.2023, https://www.forschung-und-lehre.de/lehre/urteil-zum-einsatz-von-chatgpt-6288). This needs an owner decision; the rest of this report cannot settle it.

## 1. Isley et al. and Lee et al.
- Isley: about 7,500 applications to one US public-policy master's programme, 2020-25. Essays flagged by GPTZero at high confidence, replicated with Pangram. Seven dimensions: grammar (5 points = 0-1 surface errors), style, clarity, prompt responsiveness, voice ("voice and originality"), public service, and leadership ("mentioned a specific future leadership role, and the number of details"). Weights calibrated against officers' ratings: prompt responsiveness .479, voice .226, public service .213, grammar .208, style .207, clarity .105, leadership .064. AI use was 69.3% among international applicants vs 38.6% domestic, and international applicants' mechanical gains were about twice domestic ones. Staff spotted AI at AUC 0.70. The paper quotes no essays and no officer comments.
- Lee et al.: 81,663 applicants. After 2023, surface features converged across groups. Lower-SES LLM users wrote essays with 4.3% fewer word types, MTLD 90.9 vs 95.8, and more repetition, and their admission penalty was 1.85x larger. https://arxiv.org/html/2602.17791 (PP)

## 2. Readers in their own words
- Kaplan, Nov 2025, 220 US officers: "The writing oftentimes also doesn't match the writing of other sections…" 30% ban AI essay-writing, 2% allow it (PRAC survey, https://kaplan.com/about/press-media/college-admissions-officers-survey-2025-essays-ai).
- The TUM examiners' reasons, accepted by the court: the essay differed from other applicants' "in Umfang, Struktur, Inhaltsdichte, Stil und Rechtschreibung" (length, structure, content density, style, spelling); ChatGPT given the same prompt produced "auffallende Ähnlichkeiten"; and the applicant's essay the year before was much weaker (OFF). So readers compare three things: the rest of the cohort, what a model writes for that prompt, and the applicant's own other writing.
- UCAS: AI statements read as "very academic and bland" with generic motivations (OFF).
- Türkiye Bursları: committees score "content of the letter of intent" and "consistency of preferences", then interview (OFF, https://www.turkiyeburslari.gov.tr/evaluationandselectionprocess). Chevening tells applicants to expect interview questions on the examples in their essays and to stay "in sync" with them (OFF, https://www.chevening.org/resource-hub/guidance/interviews/).
- DAAD: no official AI clause could be verified (daad.de was unreachable).

## 3. Non-native authenticity
- No study directly tests whether a flawless letter from a B2 applicant is itself a red flag. Three things point that way. Reviewers of about 80k CS peer reviews moved their "language" complaints from grammar errors to LLM vocabulary cues and tied those cues to non-native authors (PR, Lepp & Smith, FAccT 2025, https://arxiv.org/pdf/2505.08127v1). Non-native writers face a double bind: rough English is penalised, polished English is suspected (PRAC, Scholarly Kitchen 2026-09-22). And detectors flag professionally edited non-native text anywhere from 0% to 100% of the time across 13 tools (PP, arXiv 2608.26710).
- What an L2 letter looks like in measurable terms. Human L2 essays scored MTLD 66.6 vs 118 for GPT-4 and a Flesch-Kincaid grade of 12.1 vs 16.6. They use more coordination ("and… and") and fewer dependent clauses (0.57 vs 0.75 per T-unit) (PR, Frontiers in Education 2025, https://www.frontiersin.org/journals/education/articles/10.3389/feduc.2025.1616935/full).
- CEFR proxies from 6,407 Aptis scripts, B2 vs C-level writers: words over 2 syllables 7.8% vs 9.3%; English Vocabulary Profile C1+C2 words 0.82% vs 1.25% of tokens; B2-band words 2.16% vs 3.25%. The authors warn the differences are small and lexis alone cannot assign a level (OFF research report, https://textinspector.com/lexical-profiles-according-to-the-cefr/). Sentence length barely separates B2 from C1 (about 18 vs 19 words).

## 4. Textual properties: evidence vs folklore
- Sentence-length variation: human academic text CV 0.449 vs AI rewrites 0.376; 79.3% of rewrites came out flatter (PRAC working paper, https://textpulse.ai/research/ai-burstiness-sentence-length). Human news has more scattered sentence lengths and more emotional range (PR, Muñoz-Ortiz et al. 2024, https://arxiv.org/abs/2308.09067).
- Clause shape: ChatGPT clauses average 15.3 words vs 8.6 for native writers, with 2.15 vs 1.04 complex nominals per clause. Native writers use more verb phrases (2.77 vs 1.68 per T-unit) and subordinate clauses, and vary more between essays (PR, PLOS One 2025, https://journals.plos.org/plosone/article?id=10.1371%2Fjournal.pone.0329410). This fits the known Reinhart nominalisation finding. "Plain verbs" therefore has evidence behind it.
- Stance and admitting uncertainty: ChatGPT uses significantly fewer hedges, boosters, attitude markers and engagement markers than students (PR, Jiang & Hyland, ESP 2025 and Written Communication 2025, https://www.sciencedirect.com/science/article/abs/pii/S0889490625000134).
- Specific, checkable detail: forensic research shows people judge accounts rich in sensory, spatial and temporal detail as more credible (PR by analogy only, https://doi.org/10.3390/brainsci13030392). Transfer to admissions is untested.
- When GPT-4 was fed the applicant's real traits, faculty told AI from human statements only 59% of the time (PR, Can Med Educ J 2025, https://pmc.ncbi.nlm.nih.gov/articles/PMC12826822). Grounding in real facts removes much of the gap.
- Unequal paragraph sizes, "one real story", and "uneven emphasis": supported only indirectly (Ding 2007, homogenisation studies). Treat as FOLK or PRAC.

## 5. Legitimate ways to get the applicant's voice in
- Interview, then draft, then the student chooses: an LLM asked template questions, drafted three variants, and the user picked and edited. More than 380 users; users felt it was "my own thoughts being put on paper" (PR, CHI 2025, https://pmc.ncbi.nlm.nih.gov/articles/PMC12265993/).
- How much the user supplies matters: ownership rises with prompt length and plateaus once the user's input reaches 75-100% of the target length (PR, Joshi & Vogel, CUI 2025, https://arxiv.org/abs/2404.03108).
- The writer choosing what goes into the text ("content gatekeeping") keeps authenticity. Personalising from writing samples changed nothing, and readers could not tell AI-assisted from solo work (PR, Hwang et al., CSCW 2025, https://arxiv.org/html/2411.13032v1).
- Risk: AI suggestions pulled Indian writers toward Western style and stripped cultural detail (PR, Agarwal et al., CHI 2025, https://arxiv.org/abs/2409.11360).
- Free speech or dictation suits reflective writing, but its effect on voice was not measured (PR, CHI EA 2025). Drafting in L1 is normal L2 practice (PR, J. Second Language Writing 2024). Nobody has measured whether an L1 voice note turned into an L2 letter reads as the applicant's own.

## 6. Other languages
- No peer-reviewed study of LLM tells in DE/FR/TR/RU motivation letters was found. A transferable method exists: a Korean study counted words by morphology and found a shift in register. 시사하다 ("suggest") appears in 21.4% of 2026 abstracts vs 5.3% expected, while plain verbs fell to a quarter of trend (PP, https://arxiv.org/abs/2609.07447). Turkish and Azerbaijani are agglutinative too, so counts need lemmas.
- German (PRAC): "Darüber hinaus", "Zudem", "Zusammenfassend lässt sich sagen", "eintauchen", vague "innovativ", even sentence lengths.
- French (PRAC/FOLK): "C'est avec un vif intérêt que…", "je suis fermement persuadé(e)", "dynamisme et rigueur".
- Russian (PRAC): even rhythm, runs of em-dashes, errorless dry style, odd compound words (https://t-j.ru/short/ai-here/).

## Design implications for our engine
1. Get an owner ruling per funder on AI-authorship declarations (Chevening, UCAS, TUM-style declarations). The engine should warn or refuse where a false declaration would follow. CODE, using a per-programme rule.
2. Interview the student before drafting: "tell me about a moment when…", aiming for input about as long as the letter. Voice notes in Azerbaijani or Russian are fine. STUDENT INPUT.
3. Offer 2-3 drafts and let the student pick and edit; record which sentences they kept. STUDENT INPUT plus CODE.
4. Carry the student's own phrases over verbatim, keep a minimum share of them, and have code confirm they survived. CODE.
5. Cap vocabulary level against the student's measured English: EVP C1+C2 share, share of words over 2 syllables, Flesch-Kincaid grade, set per IELTS/TOEFL band. CODE.
6. Flag flat sentence lengths (CV well under ~0.45) and near-equal paragraph sizes. CODE, as a flag, not a target to game.
7. Limit noun-heavy long clauses and participial openers; prefer verbs. CODE (with a POS tagger).
8. Per-language lists of stock phrases (EN/DE/FR/RU/TR), counted by lemma; drop them or require a reason to keep them. CODE.
9. Require one concrete story with checkable particulars (place, time, object, number) from the facts ledger. MODEL CHECK, backed by a CODE ledger lookup.
10. Allow real stance and hedging ("I am not yet sure whether…") where the student supplied it; never invent it. MODEL CHECK plus STUDENT INPUT.
11. Compare the letter's level and content to the student's own sample (CV prose, test essay, email). Flag big gaps, and give the student interview prep on every example in the letter. CODE plus STUDENT INPUT.
12. Check how similar the letter is to a generic model draft for the same prompt, the test TUM used; flag if too close. MODEL CHECK (embedding similarity).
