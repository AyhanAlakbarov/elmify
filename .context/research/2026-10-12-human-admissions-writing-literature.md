# What makes an admissions letter read as human: literature review

Date: 2026-10-12. Scope: Elmify drafts master's motivation letters for mostly non-native English writers. The decision this note feeds is what a writing-quality pass should change. It builds on, and does not repeat, `docs/research/2026-09-14-letter-storytelling-evidence.md` (N-01 to N-19) and `docs/research/2026-08-21-humanizer-assessment.md`. Both were read first, from the working tree; this agent cannot run `git show`.

## Sub-questions

1. What measured differences separate human-written from LLM-written essays and personal statements? This covers lexical, syntactic, discourse and content features, plus convergence across applicants.
2. What do official admissions pages say makes a statement strong?
3. Which open-source writing-quality tools could run inside a pipeline? For each: licence, maintenance, what it checks, and which of EN/DE/FR/TR/RU it supports.
4. Which non-native features are authentic and should be kept, and which are errors worth fixing?

## Bottom line

- **The difference that matters most is ideas, not words.** Applicant essays written after ChatGPT contain more varied words, but those words express more similar ideas. The effect is strongest for applicants outside the linguistic mainstream, which describes Elmify's users.[^30][^31] Asking a model for "more varied vocabulary" makes this worse. Cutting stock words alone does not fix it.
- **Polishing an applicant's draft has a measurable cost.** In 1,973 real master's statements (84% from applicants whose first language was not English), having GPT-3.5 revise the text roughly halved the total vocabulary. Writing from scratch cut it six- to seven-fold.[^16][^17] Of everything in this review, this is the closest match to a "polish the student's draft" step.
- **The features that mark model prose are known and can be checked.** They include stock words, more present-participle clauses and nominalisations, identical "In conclusion" closers and generic opening sentences. Model text also uses fewer hedges and epistemic markers ("I think", "it is believed").[^6][^7][^11][^12][^13][^14][^18]
- **Readers ask for the same things everywhere:** specific, quantified evidence; showing rather than telling; little autobiography; and reasons for choosing this programme that would not fit any other.[^34][^35][^38][^41][^43][^46]
- **Tools: none of them catches "generic content".** Each one only flags surface patterns. The only candidate that covers all five letter languages (EN/DE/FR/RU, with TR missing) is LanguageTool, and it checks grammar, not genericness.
- **Non-native features:** composition scholars say to judge whether the text works as a whole and to fix only two or three issues per writer. Detectors misread the narrower word choice typical of non-native writers as machine text.[^74][^76][^77][^78]

## 1. Measured differences between human and LLM writing

### Lexical

- **Excess style words** (Kobak et al., 15.1 M PubMed abstracts). Rarer words with strong excess usage included *delves* (28.0× expected), *underscores* (13.8×) and *showcasing* (10.7×).[^1] At least 13.5% of 2024 abstracts went through an LLM.[^2] Of the 2024 excess style words, 66% were verbs and 14% adjectives.[^3] Use was higher in China, South Korea and Taiwan (about 0.20) than in the UK and Australia (about 0.05).[^4] So non-native authors pick these words up more, which matters for Elmify's users.
- **Fiction-style vocabulary in every genre** (Reinhart et al., Biber features). GPT-4o used *camaraderie, palpable, tapestry, intricate* at more than 100 times the human rate.[^8] "Tapestry" appeared in 23% of GPT-4o outputs.[^8b] The authors read the cluster as "a preference for grandiose, if hollow, summative sentences".[^9]
- **Admissions-specific word list** (Zhao et al., Fordham master's applications in CS and data science). GPT-3.5 favoured "additionally", "wholeheartedly", "unwavering" and "emphasis".[^18] The words humans preferred included contractions, an abbreviation ("CS"), a misspelling ("programing") and possessives.[^20] The AI also overused adverbs where humans used a plain subject-predicate structure.[^21]
- **Peer reviews** (Liang et al., ICLR 2024 and others). Between 6.5% and 16.9% of review text could have been substantially modified by LLMs.[^5] The reviews themselves were not read for word lists here, so the vocabulary claims rest on Kobak, Reinhart and Zhao.

### Syntactic

- Instruction-tuned models use present participial clauses at 2 to 5 times the human rate[^6] and nominalisations at 1.5 to 2 times the human rate.[^7] Instruction tuning made output "less human, not more".[^10]
- In argumentative essays, the GPT models used more nominalisations and more complex sentences, while students used more modal and epistemic constructions.[^11][^12]
- **Sentence-length variance ("burstiness"): no admissions-specific measurement was found in this pass.** Prior note N-07's 93–99% stylometric figure was not re-verified here. See Open questions.

### Discourse and structure

- All ChatGPT essays began their concluding section the same way ("In conclusion, [...]").[^13] Their opening sentences were "very similar", each a general statement built from the topic's main concepts.[^14]
- AI-generated statements had more, but shorter, paragraphs than the human ones.[^19]
- Hedging runs the opposite way from common belief. Students used more modals and epistemic markers than the models.[^12] A pass that deletes every "I think" removes a human marker.
- Readers who use LLMs often spot AI text almost perfectly (one error in 300 articles, by majority vote). They rely on "AI vocabulary" but also on formality, originality and clarity.[^22]

### Content and homogenisation

- **Admissions essays converge after ChatGPT.** Across more than 160,000 US admissions essays, AI-assisted and post-ChatGPT essays used more varied words, but those words "actually expressed increasingly homogeneous ideas".[^30] The effect was disproportionate "among applicants outside racial and linguistic mainstreams".[^31] Source: PsyArXiv preprint, Moon, Kushlev, Bank and Green, 2025.
- **Writing like a particular demographic cannot be prompted into a model.** Across 30,000 applicants, prompting a demographic identity was "remarkably ineffective".[^24] Prompted and unprompted model essays resembled each other more than they resembled human essays.[^23] Model essays vary less than human ones, and most resemble essays by privileged male applicants.[^25][^26]
- **Co-writing studies.** Writing with InstructGPT (but not base GPT-3) significantly reduced diversity.[^27] The drop came from the model's contributions, not the users' own text.[^28] Stories written with ideas from a model are more similar to each other than stories written by people alone.[^29] (Doshi & Hauser, arXiv preprint; the version of record is in *Science Advances* 10(28), 2024, which could not be fetched.)
- **Effect on outcomes.** In 81,663 applications, surface linguistic features converged after 2023.[^33] More estimated LLM use went with a larger drop in predicted admission for lower-income applicants than for higher-income ones.[^32]
- **Quality versus sameness.** Teachers rated ChatGPT essays above student essays.[^15] Model text is not worse writing. It is the same writing.

**Where sources disagree on lexical diversity.** Zhao found AI vocabulary much smaller (GPT-3.5).[^17] Herbold found GPT-4 more lexically diverse than students.[^11] Moon found word diversity rising while idea diversity fell.[^30] The direction depends on the model. Idea-level sameness is the consistent finding, so the pass should not chase type-token ratio.

## 2. What admissions readers say a strong statement does

All sources in this section are official university or funder pages. Prior note §2.3 already covers DAAD, Göttingen, KTH, TU Delft, Leiden, Chevening and others.

| Theme | Primary wording |
|---|---|
| Evidence over adjectives | "include concrete and quantitative experiences"[^41]; "Quantify your experiences to show concrete impact"[^43]; "Demonstrate everything by example"[^35]; "give specific examples… don't just simply tell them"[^38] |
| Actions, not feelings | "Describe actions, not just changes in your internal mental or emotional state"[^44] |
| Little autobiography | Berkeley: "don't spend a great deal of time on autobiography"[^34]; MIT: "your unique research story, not your life story"[^42]; Cornell: "academically focused essay, not necessarily a personal essay"[^39] |
| Research described as facts | With whom, project title, responsibilities, outcome[^36] |
| Fit specific to the programme | Berkeley: why it is "a good intellectual fit"[^37]; LSE: avoid rankings and "generic statements about London"[^46]; "specific to the programme(s) applied for"[^47] |
| The statement is a writing sample | Cornell: it "Shows your communication style and ability"[^40] |
| Authorship and AI | LSE: "all your own work"[^48]; DAAD allows AI with disclosure, but "Applicants' unique qualities and characteristics should remain evident"[^49][^50] |

**Conflict.** MIT's CommLab says to "echo" the programme's own wording.[^45] Göttingen (prior note §2.3) says "Do not retell the information about the programme from our web page". The two fit together if the letter names a specific feature and gives the applicant's own reason for it, without paraphrasing the programme's description of itself.

## 3. Open-source tools usable inside a pipeline

**How the list was built:** an Exa search ("open-source prose linter … clichés, weasel words, overused AI phrases", limited to github.com, 15 results) and a Brave search ("open source prose linter Vale proselint write-good LanguageTool comparison"). Most Exa results were new single-author "slop" linters with 0–13 stars (wsc, deslop, slop-lint, unslop/noslop, nabokov, slop-cop, no-slop, defluff, sloplint, slopbuster, llmstrip). Only `slop-guard` (161 stars) is assessed below. `blader/humanizer` is already assessed and pinned (v3.0.0); see the humanizer note.

| Tool | What it checks | Licence | Languages | Maintenance (GitHub API, 2026-10-12) |
|---|---|---|---|---|
| **Vale** | A rules framework with no built-in opinions;[^51] YAML rules (word lists, regex, part-of-speech, readability); runs offline[^52] | MIT (API) | Rules are regex, so any language is possible in principle, but you write the rules yourself. Built-in non-English support is **Unverified** | Last push 2026-10-06; 6.2k stars; one maintainer[^53] |
| **proselint** | English usage lint: clichés, hedging,[^56] metadiscourse,[^56b] weasel words, jargon, redundancy | BSD[^57] | English only[^55] | GitHub copy is a mirror; main repo is on Codeberg. Last push 2026-09-04 |
| **write-good** | Passive voice, weasel words, adverbs,[^59] "So"/"There is" sentence openers, clichés, wordy phrases | MIT (API) | English;[^58] a third-party German extension exists[^60] | Last push 2025-03-10 (stale) |
| **LanguageTool** | Grammar, spelling and style rules; self-hostable server | LGPL 2.1+[^62] | EN/DE/FR yes;[^61][^63][^64] RU listed (892 XML rules, table read 2026-10-12); **no Turkish** in the language table | Last push 2026-10-12; very active |
| **Harper** | Fast offline grammar checker | Apache-2.0 (API) | English only[^65] | Last push 2026-10-12; 16k stars |
| **textstat** | Readability formulas, syllable/word/sentence counts | MIT (API) | English by default;[^67] some formulas have DE/FR/RU variants via Pyphen[^68] | Last push 2026-10-05 |
| **slop-guard** | Scores 0–100 with 24 rules and 200+ heuristics:[^70] stock words, assistant tone, contrast tells, aphoristic closers, sentence and paragraph rhythm[^71] | MIT[^72] | English (all rules are English phrase lists, inferred from README) | Created 2026-02; v0.5.x; one author |

**Code read:** none of these tools' source was audited. Only slop-guard's `pyproject.toml` was read. It declares two pinned runtime dependencies (`mcp==1.26.0`, `typing-extensions`) and three console scripts, with no install hooks. Nothing malicious or obfuscated was seen in that file. Earlier, the 2026-09-14 storytelling note found that `fromleda/text-humanizer`'s code did not match its README.

**Fit for the decision.** Every tool here flags surface patterns, which are what §1 measures at the word and syntax level. None measures idea-level sameness, the dominant finding in §1. Vale is the natural host for a Elmify-specific rule set (the stock words from [^1][^8][^18], "In conclusion", generic openers), because rules are plain files and it runs offline. LanguageTool is the only multilingual grammar layer, and Turkish has no coverage. No tool gives German, French, Turkish or Russian lists of model-overused words. **No published evidence was found** for stock-word lists in those languages.

## 4. Non-native features: keep versus fix

- **Keep: features carried over from other languages and rhetorical traditions.** The CCCC statement says multilingual writers "may (intentionally or unintentionally) employ features of multiple languages and literacies in their English writing".[^73] It also says where the main argument goes, and how sources are used, rest on cultural assumptions.[^75]
- **Fix: two or three priority issues, judged against the whole text.** Evaluators should look for "rhetorically effective features" rather than the one or two that stand out as problems.[^74] Teachers should prioritise "two or three mechanical or stylistic issues".[^76]
- **Keep: hedges and epistemic markers.** Students use more of them than models.[^12] They are part of a human voice, not filler.
- **Keep: simple word choice, contractions and field abbreviations.** In real master's statements these were human markers. Formal adverb-heavy vocabulary was the AI marker.[^20][^21] Detectors flag non-native writing because of its "constrained linguistic expressions".[^77][^78] Nothing in the evidence supports enriching vocabulary to sound native. Doing so moves the text toward the homogenised register.[^30]
- **Fix: errors that change meaning.** Error-gravity research says faculty correct errors that change meaning (word choice, verb tense/aspect) more often than article or preposition slips. **Unverified here:** Roberts & Cimasko (2008, *J. Second Language Writing*) and Vann et al. (1984, *TESOL Quarterly*) were found only as search-index abstracts; the publisher pages and the author's PDF did not load as text.
- **Prompting is not a substitute.** Telling a model to "write as a [demographic]" does not reproduce how that group writes.[^24] Keeping the student's own sentences is the only way to keep their voice.

## What this implies for the pass (inference from the above, not a cited claim)

1. Replace or delete measured stock words and set phrases ([^1][^8][^18]; "In conclusion"; generic topic-sentence openers[^13][^14]). Do this as lint findings against the letter, not as a free rewrite. This is consistent with the humanizer note's no-rewrite-pass architecture.
2. Do not raise lexical variety or formality. Leave hedges, contractions and plain verbs alone.
3. Flag sentences that would make sense in any applicant's letter, using the portability test already in the design (A10/N-15). This is the only check aimed at the idea-level sameness finding, and no off-the-shelf tool does it.
4. Fix only meaning-changing errors in student-supplied text, and record them, rather than polishing everything. Model revision halves vocabulary.[^17]
5. Across letters: measure similarity between Elmify's own letters to the same programme (the homogenisation risk[^30][^23]). No tool exists for this. It is a build item if wanted.

## Tools and sources

Used: Exa, Brave, scrapling `get`/`bulk_get`. Not needed: Context7 and Tavily. Unreachable: MIT EECS faculty page (404); Göttingen 648936 (empty shell); PMC copy of Doshi & Hauser (HTTP 203); DOAJ (403); De Gruyter IRAL L2-lexis paper (202, empty); the Roberts & Cimasko author PDF (binary); and Semantic Scholar abstracts withheld by the publisher.

## Sources

[^1]: https://arxiv.org/html/2406.07016 "Less common words with strong excess usage included delves"
[^2]: https://arxiv.org/abs/2406.07016 "This excess word analysis suggests that at least 13.5% of 2024 abstracts were processed with LLMs."
[^3]: https://arxiv.org/html/2406.07016 "out of all 379 excess style words in 2024, 66% were verbs and 14% were adjectives"
[^4]: https://arxiv.org/html/2406.07016 "while countries like China, South Korea, and Taiwan showed"
[^5]: https://arxiv.org/abs/2403.07183 "between 6.5% and 16.9% of text submitted as peer reviews to these conferences could have been substantially modified by LLMs"
[^6]: https://arxiv.org/html/2410.16107 "the instruction-tuned LLMs used present participial clauses at 2 to 5 times the rate of human text"
[^7]: https://arxiv.org/html/2410.16107 "They also use nominalizations at 1.5 to 2 times the rate of humans"
[^8]: https://arxiv.org/html/2410.16107 "and intricate at more than 100 times the rate of humans"
[^8b]: https://arxiv.org/html/2410.16107 "“tapestry” appeared in 23% of GPT-4o outputs"
[^9]: https://arxiv.org/html/2410.16107 "may signal a preference for grandiose, if hollow, summative sentences"
[^10]: https://arxiv.org/html/2410.16107 "instruction tuning appears to make the model output less human, not more"
[^11]: https://www.nature.com/articles/s41598-023-45644-9 "the GPT models use more nominalizations and have higher sentence complexity"
[^12]: https://www.nature.com/articles/s41598-023-45644-9 "whereas the students make more use of modal and epistemic constructions"
[^13]: https://www.nature.com/articles/s41598-023-45644-9 "which for instance is reflected by the identical beginnings of the concluding sections of all ChatGPT essays"
[^14]: https://www.nature.com/articles/s41598-023-45644-9 "The initial sentences of each essay are also very similar starting with a general statement using the main concepts of the essay topics."
[^15]: https://www.nature.com/articles/s41598-023-45644-9 "ChatGPT generates essays that are rated higher regarding quality than human-written essays"
[^16]: https://www.nature.com/articles/s41598-024-77847-z "84% did not list English as their first language"
[^17]: https://www.nature.com/articles/s41598-024-77847-z "roughly six to seven times the size of the vocabularies for the corresponding AI-generated documents and twice the size of vocabularies used in the AI-revised documents"
[^18]: https://www.nature.com/articles/s41598-024-77847-z "GPT-3.5 seems to heavily favor words like “additionally,” “wholeheartedly,” “unwavering,” and “emphasis.”"
[^19]: https://www.nature.com/articles/s41598-024-77847-z "the AI text generation process yields more, but shorter, paragraphs for both the LORs and SOIs"
[^20]: https://www.nature.com/articles/s41598-024-77847-z "the human-preferred list includes one abbreviation (“CS”), one misspelled word (“programing”), and many possessive words"
[^21]: https://www.nature.com/articles/s41598-024-77847-z "a significant overuse of adverbs by AI, contrasting with humans’ preference for a simpler subject-predicate structure"
[^22]: https://arxiv.org/abs/2501.15654 "misclassifies only 1 of 300 articles"
[^23]: https://arxiv.org/abs/2503.20062 "The demographically prompted and unprompted synthetic texts were also more similar to each other than to the human text"
[^24]: https://arxiv.org/abs/2503.20062 "prompting a specific sociodemographic identity is remarkably ineffective in aligning the model"
[^25]: https://link.springer.com/article/10.1186/s40537-024-00986-7 "human-authored essays exhibit more variability across various individual writing style features (e.g., verb usage) than AI-generated essays"
[^26]: https://link.springer.com/article/10.1186/s40537-024-00986-7 "the AI-generated essays are most similar to essays authored by students who are males with higher levels of social privilege"
[^27]: https://arxiv.org/abs/2309.05196 "writing with InstructGPT (but not the GPT3) results in a statistically significant reduction in diversity"
[^28]: https://arxiv.org/abs/2309.05196 "the user-contributed text remains unaffected by model collaboration"
[^29]: https://arxiv.org/abs/2312.00506 "GenAI-enabled stories are more similar to each other than stories by humans alone"
[^30]: https://www.ebi.ac.uk/europepmc/webservices/rest/search?query=EXT_ID:PPR1052045%20AND%20SRC:PPR&resultType=core&format=json "but the increasingly diverse words actually expressed increasingly homogeneous ideas"
[^31]: https://www.ebi.ac.uk/europepmc/webservices/rest/search?query=EXT_ID:PPR1052045%20AND%20SRC:PPR&resultType=core&format=json "emerged disproportionately among applicants outside racial and linguistic mainstreams"
[^32]: https://arxiv.org/abs/2602.17791 "increased estimated LLM use was more strongly associated with declines in predicted admission probability for lower SES applicants"
[^33]: https://arxiv.org/abs/2602.17791 "we observe post-2023 convergence in surface-level linguistic features"
[^34]: https://grad.berkeley.edu/admissions/application-process/writing-your-statements/ "don’t spend a great deal of time on autobiography"
[^35]: https://grad.berkeley.edu/admissions/application-process/writing-your-statements/ "Demonstrate everything by example; don’t say directly that you’re a persistent person, show it."
[^36]: https://grad.berkeley.edu/admissions/application-process/writing-your-statements/ "Indicate with whom, the title of the project, what your responsibilities were, and the outcome."
[^37]: https://grad.berkeley.edu/admissions/application-process/writing-your-statements/ "Please be specific about why UC Berkeley would be a good intellectual fit for you."
[^38]: https://gradschool.cornell.edu/inclusion/recruitment/prospective-students/writing-your-statement-of-purpose/ "Whenever possible, give specific examples and illustrate the points you are making, don’t just simply tell them."
[^39]: https://gradschool.cornell.edu/inclusion/recruitment/prospective-students/writing-your-statement-of-purpose/ "this is an academically focused essay, not necessarily a personal essay"
[^40]: https://gradschool.cornell.edu/inclusion/recruitment/prospective-students/writing-your-statement-of-purpose/ "Shows your communication style and ability."
[^41]: https://mitcommlab.mit.edu/eecs/commkit/graduate-school-statement-of-purpose/ "include concrete and quantitative experiences, accomplishments, and qualifications."
[^42]: https://mitcommlab.mit.edu/eecs/commkit/graduate-school-statement-of-purpose/ "The statement of purpose should tell your unique research story, not your life story."
[^43]: https://mitcommlab.mit.edu/eecs/commkit/graduate-school-statement-of-purpose/ "Quantify your experiences to show concrete impact."
[^44]: https://mitcommlab.mit.edu/eecs/commkit/graduate-school-statement-of-purpose/ "Describe actions, not just changes in your internal mental or emotional state."
[^45]: https://mitcommlab.mit.edu/eecs/commkit/graduate-school-statement-of-purpose/ "See what language they use to describe themselves, and echo that language in your essay."
[^46]: https://www.lse.ac.uk/study-at-lse/Graduate/Prospective-students/Supporting-documents/Statement-of-academic-purpose "Please avoid general statements about LSE’s performance in global rankings, and generic statements about London being a global/cosmopolitan centre of excellence."
[^47]: https://www.lse.ac.uk/study-at-lse/Graduate/Prospective-students/Supporting-documents/Statement-of-academic-purpose "Are well-written, well-structured and specific to the programme(s) applied for"
[^48]: https://www.lse.ac.uk/study-at-lse/Graduate/Prospective-students/Supporting-documents/Statement-of-academic-purpose "Are all your own work. If we discover this is not the case, your application may be cancelled"
[^49]: https://www.daad.de/en/studying-in-germany/scholarships/information-for-scholarship-applicants/ "Applicants’ unique qualities and characteristics should remain evident as these play an important role in the selection process."
[^50]: https://www.daad.de/en/studying-in-germany/scholarships/information-for-scholarship-applicants/ "The use of AI tools must be clearly indicated by stating in your documents that text passages were created with the help of an AI tool."
[^51]: https://github.com/vale-cli/vale "Vale doesn't ship opinions of its own."
[^52]: https://github.com/vale-cli/vale "Nothing leaves your machine: no account, no upload, and no training on your writing."
[^53]: https://github.com/vale-cli/vale "the sole developer of Vale"
[^55]: https://codeberg.org/amperser/proselint "a linter for English prose. A linter is a computer program"
[^56]: https://codeberg.org/amperser/proselint "Avoid undermining yourself with uncertainty"
[^56b]: https://codeberg.org/amperser/proselint "Avoid discussing the discussion"
[^57]: https://codeberg.org/amperser/proselint "The project is licensed under the BSD license."
[^58]: https://github.com/btford/write-good "Naive linter for English prose for developers who can't write good"
[^59]: https://github.com/btford/write-good "Checks for adverbs that can weaken meaning: really, very, extremely, etc."
[^60]: https://github.com/btford/write-good "A basic extension for the German language"
[^61]: https://github.com/languagetool-org/languagetool "open-source proofreading software for English, Spanish, French, German, Portuguese, Polish, Dutch, and more than 20 other languages"
[^62]: https://github.com/languagetool-org/languagetool "The LanguageTool core (this repo) is freely available under the LGPL 2.1 or later."
[^63]: https://dev.languagetool.org/languages "German Variants for: Austria, Germany, Swiss"
[^64]: https://dev.languagetool.org/languages "French Variants for: Belgium, Canada, Switzerland"
[^65]: https://github.com/Automattic/harper "Harper currently only supports English"
[^67]: https://github.com/textstat/textstat "By default functions implement algorithms for english language."
[^68]: https://github.com/textstat/textstat "Uses the Python module Pyphen for syllable calculation in most languages"
[^70]: https://github.com/eric-tramel/slop-guard "The default pipeline loads 24 configurable rules backed by 200+ literal and structural heuristics."
[^71]: https://github.com/eric-tramel/slop-guard "repeated 4-8 word phrases, copula chains, extreme long sentences, aphoristic closers, and uneven paragraph cadence"
[^72]: https://raw.githubusercontent.com/eric-tramel/slop-guard/main/pyproject.toml "License :: OSI Approved :: MIT License"
[^73]: https://cccc.ncte.org/cccc/resources/positions/secondlangwriting/ "they may (intentionally or unintentionally) employ features of multiple languages and literacies in their English writing"
[^74]: https://cccc.ncte.org/cccc/resources/positions/secondlangwriting/ "Writing instructors should look for evidence of a text’s rhetorically effective features, rather than focus only on one or two of these features that stand out as problematic."
[^75]: https://cccc.ncte.org/cccc/resources/positions/secondlangwriting/ "whether the main argument of an essay should appear at the beginning or end, or how sources should be used, are deeply rooted in specific cultural assumptions"
[^76]: https://cccc.ncte.org/cccc/resources/positions/secondlangwriting/ "prioritizing two or three mechanical or stylistic issues that individual multilingual writers should focus on"
[^77]: https://arxiv.org/abs/2304.02819 "these detectors consistently misclassify non-native English writing samples as AI-generated"
[^78]: https://arxiv.org/abs/2304.02819 "GPT detectors may unintentionally penalize writers with constrained linguistic expressions"

## Open questions

- **Sentence-length variance:** no paper fetched here measures it for human versus LLM admissions letters. The 93–99% stylometric figure in prior note N-07 was not re-verified.
- **Stock-word lists for German, French, Turkish and Russian:** no published, measured lists were found. Every list above is English.
- **Error gravity:** Roberts & Cimasko (2008) and Vann et al. (1984) were not readable as text. The "fix meaning-changing errors first" ordering is therefore Unverified in this file.
- **Licences and push dates for Vale, write-good, Harper and textstat** come from the GitHub API JSON. That source is not quote-checkable in this format.
- **Recency:** most measured studies use GPT-3.5, GPT-4 or GPT-4o. None tests the models Elmify uses (OpenAI extraction model, Sonnet 5, GLM), so the specific stock words may have shifted.
- **The PsyArXiv homogenisation paper** (Moon et al. 2025) is a preprint. A later version on the same theme reports 372,793 applicants, but it was seen only in a search index and not fetched.
