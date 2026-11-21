# A. Writer prompts — notes (fetched 2026-09-28)

## OpenAI
- developers.openai.com/api/docs/guides/prompt-guidance [OD, GPT-6 Astra era, undated page]: specify writing style; "clear, concise paragraphs, each developing one main idea"; "prefer active voice and direct statements". It DOES use a short banned list: "Avoid using slop words or phrases like 'Bottom Line:' ... 'delve,' 'foster,' 'leverage'" and "contrastive framing such as 'X, not Y'". → OpenAI itself uses a short negative list alongside positive description.
- GPT-5.5/5.6 guides (via Simon Willison 2026-04-25 simonwillison.net/2026/apr/25/gpt-5-5-prompting-guide/ [PR summary of OD]; Decrypt [press]): outcome-first; define target, success criteria, constraints, context, let model choose path; trim repeated rules; leaner prompts +10–15% eval, −41–66% tokens (per Decrypt reporting of OpenAI guide — secondary).
- GPT-5 prompting guide (developers.openai.com/cookbook/examples/gpt-5/gpt-5_prompting_guide) [OD 2025]: contradictory instructions waste reasoning; `verbosity` API param for length.

## Anthropic [OD] platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices (fetched 2026-09-28)
- "Tell Claude what to do instead of what not to do" (e.g. "Your response should be composed of smoothly flowing prose paragraphs").
- "Match your prompt style to the desired output" — markdown in prompt → markdown out. So: a prose writer prompt should itself be mostly prose, not a wall of bullets.
- Explain WHY behind instructions → better targeting.
- Examples: relevant, diverse, wrapped in <example> tags; 3–5 examples. Positive examples of desired style beat instructions about what to avoid.
- Long context: data at top, query/instructions at end: "Queries at the end can improve response quality by up to 30 percent".
- Role in system prompt: "Even a single sentence makes a difference".
- Prefill no longer supported from 4.6 models → use direct instructions / strip preamble in post-processing.
- Opus 5: written deliverables longer; add explicit length calibration.

## Google [OD] ai.google.dev/gemini-api/docs/prompting-strategies; Vertex "gemini 3 prompting guide"
- Behavioural constraints/role in System Instruction or at very top; for large context put specific instructions at END after data. (Also Phil Schmid [PR] philschmid.de/gemini-3-prompt-practices.)
- Structure: rules → context → definitions → task → output format.

## Chinese vendors
- DeepSeek API docs api-docs.deepseek.com/quick_start/parameter_settings [OD]: temperature table — Creative Writing/Poetry 1.5, Translation 1.3, Coding 0.0. (For fact-bound letters, 1.5 raises invention risk; our use case is closer to "general conversation" 1.0–1.3.)
- No official Moonshot/Zhipu/Qwen writing-prompt guides found in this search; only SEO/practitioner comparisons (aiwave.live, featherless.ai) [F]. Claim "Chinese models more literal; prefer explicit structured prompts" = folklore tier.

## Negative instructions / pink elephant
- "Don't Think of the White Bear: Ironic Negation in Transformer Models Under Cognitive Load" arXiv 2511.12381 (2025-11-15) [peer-review pending, preprint]: rebound (forbidden token surfacing) emerges immediately after negation and INTENSIFIES with longer/semantic distractor text; repetition supports suppression. Implication: a long banned list placed far from the point of generation, followed by lots of content, is the worst case.
- "Negation: A Pink Elephant in the LLMs' Room?" arXiv 2503.22395 (2025) [preprint]: negation tokens have limited effect on representations.
- 16x.engineer blog 2025-08-05 [folklore/practitioner]: anecdotal only.
- Synthesis: keep banned list SHORT (≤10 items, highest-frequency offenders), paired with positive style description; enforce the rest in code (the stylometry checker already does). Don't put a 100-word banned list in the writer prompt.

## Length control
- Plan-and-Write arXiv 2511.01807 (2025-11-03) [preprint]: planning + explicit word counting in prompt, up to +37.6% length adherence across 6 LLMs, best for short-to-medium constraints; quality maintained.
- Prompt-based one-shot exact length (countdown markers) arXiv 2508.13805 (2025) [preprint]: GPT-4.1 strict compliance <30% naive → >95% with countdown prompt.
- LIFEBench: sizeable gaps in length obedience in SOTA models.
- → Per-paragraph budgets (small targets) are easier than one global 800; check in code; tolerance ±15–20%.

## JSON vs plain text
- "Let Me Speak Freely?" arXiv 2408.02442, EMNLP 2024 Industry [peer-reviewed]: format restrictions (esp. JSON mode) degrade reasoning; help classification. Prose quality under JSON not directly measured, but escaping/quoting long text in JSON is a known source of truncation/escape bugs [practitioner].
- → Ask for plain text with paragraphs separated by blank lines (or one light delimiter line per paragraph like "§2"), parse in code.

## Few-shot for prose
- Anthropic: diverse examples to avoid unintended patterns.
- Homogenisation: ScienceDirect 2025 (S294988212500091X) [peer-reviewed]: human essays add 2–8× more semantic diversity than GPT-4 essays. arXiv 2509.14543 (EMNLP Findings 2025) [peer-reviewed]: LLMs struggle to imitate implicit style; narrow exemplar clusters reduce stylistic diversity.
- → Full-letter exemplars risk copied structure/phrases across students; prefer 2–3 SHORT excerpts showing a quality (concrete detail, plain sentence) from different letters, rotated; add n-gram overlap check vs exemplars in code.

## Placeholders
- No direct benchmark found on placeholder preservation in free-generation. Anonymisation literature (arXiv 2603.17217, 2026; ACM RAIE 2026) uses typed numbered placeholders [PERSON_1] reused consistently. Practitioner consensus: use distinctive, bracket-typed tokens unlikely in prose (e.g. {{APPLICANT_NAME}}), verify exact count/presence in code, reinject after. Folklore tier for reliability claims → MEASURE: count placeholders in vs out on every generation.

## Qwen sampling (huggingface.co/Qwen/Qwen3-8B etc. model cards) [OD]
- presence_penalty 0–2 reduces repetition, but "a higher value may occasionally result in language mixing and a slight decrease in model performance". Non-thinking text tasks card suggests presence_penalty up to 1.5–2.0. → For Turkish/Russian/Azerbaijani letters, language-mixing is a real failure mode of Chinese models: keep presence_penalty low and run a per-sentence language-ID check in code (e.g. fastText lid.176 / lingua).
# B/C/D notes (fetched 2026-09-28)

## B. Plan-then-write
- LongWriter / AgentWrite, ICLR 2025 [peer-reviewed] proceedings.iclr.cc/.../59f278de1619bdb6b53fd04e8e0976e0-Paper-Conference.pdf: plan with per-paragraph target word counts, then generate each paragraph sequentially WITH previous paragraphs in the prompt.
- "A Multi-Framework Comparison of Outline Stages in Long-Form Generation" arXiv 2608.26177 (2026-08-13) [preprint]: outline-first beats non-outline on faithfulness (outline consistency 3.39 → 4.71 /5); per-paragraph word budgets (SuperWriter) best in single-chapter mode; outline quality only moderately predicts writing quality (Spearman ~0.45–0.58) → plan and expansion are separate engineering problems.
- Outline-guided Text Generation, NAACL 2025 Industry (aclanthology 2025.naacl-industry.20) [peer-reviewed].
- Synthesis for ~800 words (a "single chapter"): whole-letter in ONE call from a structured plan keeps voice and transitions; per-paragraph calls only if a paragraph fails, and then with the full letter as context. Our budget = ~5 paragraphs × 120–180 words — within one generation easily.

## C. Targeted repair
- Kamoi et al., TACL 2024 "When Can LLMs Actually Correct Their Own Mistakes?" arXiv 2406.01297 [peer-reviewed]: no successful self-correction from prompted-LLM feedback except in suited tasks; works well with RELIABLE EXTERNAL feedback. → our code checks + Jev are external feedback: good.
- RARR, ACL 2023 [peer-reviewed] arXiv 2210.08726: research-then-revise, edits only unsupported spans; preserves original intent >90% vs 6–40% for EFEC/LaMDA.
- Self-Refine, NeurIPS 2023 [peer-reviewed] arXiv 2303.17651: most gain in first 1–2 rounds, diminishing after. Error analysis of feedback-driven refinement (via emergentmind summary of Self-Refine): ignoring feedback 25%, introducing a new problem 20%, not robust 10% [secondary summary — verify in paper appendix before quoting].
- Detect–Remask–Repair arXiv 2606.12807 (2026) [preprint]: localized repair better when only a few claims are unsupported; preserves supported content.
- Span-guided vs global rewrite (detox) arXiv 2607.26795 (2026) [preprint]: localized edits risk "residual harm" (removing the token but keeping the proposition); global rewrite risks over-modification. Localized wins for concrete factual substitutions/numeric updates; coordinated multi-claim changes favour regeneration.
- Chakrabarty et al., CHI 2025 "Can AI writing be salvaged?" arXiv 2409.14509 [peer-reviewed]: 7-category idiosyncrasy taxonomy (clichés, unnecessary exposition, purple prose…), LAMP 1,057 paragraphs; automatic editing helps but editors prefer human revisions.
- Synthesis: rewrite flagged sentence with ±1 neighbouring sentence as context, give the model the specific failed check + the allowed facts; re-run ALL checks on the whole letter after repair (a fix can break length, flow, or introduce a new claim); one round; if still failing → drop sentence (if the paragraph still answers its question) or hold. Residual-harm risk: after an "inflated role" rewrite the proposition can survive with softer words → recheck the claim, not just the word.

## D. Fact/claim checking
- MiniCheck, EMNLP 2024 [peer-reviewed] arXiv 2404.10774: sentence-level check without decomposition; MiniCheck-FT5 770M 74.7% balanced accuracy on LLM-AggreFact ≈ GPT-4 75.3%, 400× cheaper; training teaches multi-sentence synthesis.
- LLM-AggreFact leaderboard llm-aggrefact.github.io (fetched 2026-09-28, undated): Bespoke-MiniCheck-7B 77.4%, Claude-3.5 Sonnet 77.2%, Granite Guardian 3.3 8B 76.5%, FactCG-DeBERTa-L 0.4B 75.6%. → ceiling for grounding checkers ≈ 75–78% BAcc on hard mixed data — i.e., roughly 1 in 4–5 mistakes; must not be the only gate for names/numbers (code does those).
- "Decomposition Dilemmas", NAACL 2025 [peer-reviewed] arXiv 2411.02400: decomposition has inconsistent effect; trade-off between accuracy gain and decomposition noise; with MiniCheck verifier most decomposition methods LOWERED balanced accuracy.
- VeriScore (2024) [peer-reviewed EMNLP Findings]: extract only verifiable claims; FActScore extracts unverifiable claims from open-ended text. DnDScore arXiv 2412.13175: decontextualise + decompose. VeriFastScore arXiv 2505.16973 (2025).
- Exaggeration / claim strength: Wright & Augenstein EMNLP 2021 [peer-reviewed] aclanthology 2021.emnlp-main.845: best approach = classify claim strength of source and target separately, then compare. RIGOURATE arXiv 2601.04350 (2026). → For "led vs participated": a closed ROLE-LEVEL scale (observed < assisted < contributed < co-led < led/sole) classified for the sentence AND stored per fact; compare in code. Don't ask "is this inflated?" directly.
- Nothing found on résumé role-inflation detection specifically (gap).
- Opinions/plans: VeriScore-style "is this a verifiable claim about the applicant's past?" gate first; plans/motivations ("I want to…") are not checked for truth, only for "does it presuppose a fact?" (e.g., "building on my three publications" presupposes three publications).
# E. Stylometry as code — notes (fetched 2026-09-28)

## Features with published evidence
- Reinhart et al., PNAS 2025-02-25 "Do LLMs write like humans?" doi 10.1073/pnas.2422455122 / arXiv 2410.16107 [peer-reviewed]: Biber features; instruction-tuned LLMs use MORE nominalisations and present participial clauses; differences persist with scale, larger for instruct than base models. English only (Llama 3, GPT-4o).
- "Interpretable Stylistic Variation in Human and LLM Writing Across Genres, Models, and Decoding" arXiv 2604.14111 (2026-04-15) [preprint]: 67 Biber features, RF AUC 0.9775. LLM overuse: that-clauses as subjects, contractions, past participial clauses, nominalisations, sentence relatives ("noun-heavy, information dense"). Underuse: wh-relatives, pied-piping, concessive subordinators, synthetic negation, discourse particles. Lexical diversity (TTR) most important feature. GENRE effect > source effect → thresholds must be calibrated per genre (motivation letters), not borrowed.
- arXiv 2412.03025 "Human Variability vs Machine Consistency" [preprint]: humans far more dispersed across 250 features; 87% LR accuracy; caveat: length confound.
- Temporal flattening arXiv 2604.12097 (2026) [preprint]; sentence-length variance claims widespread; textsight.ai blog [folklore].
- Kobak et al., Science Advances 2025 eadt3813 [peer-reviewed]: excess vocabulary in 15M PubMed abstracts ("delve", "underscore", "intricate" >1000% rise 2022–24). English. Lists: github.com/berenslab/llm-excess-vocab.
- Juzek et al. "AI-Associated Lexical Shifts Across 34 Languages" arXiv 2605.25358 (2026-05-25) [preprint]: GPT-4.1-mini vs WMT News Crawl; LPR-ranked AI-overused lemmas for 34 languages incl. German (betonen, innovativ), French (insister, importance), Russian (подчеркивать, инновационный), Turkish (vurgula), Kazakh, Kyrgyz. NOT Azerbaijani. Emphasis verbs overused in 24/34 languages; importance nouns 20; innovation adjectives 18. Data: github.com/tjuzek/ai-34-languages, aiwordexplorer.com. News genre, one model → treat as seed list, re-rank on own letters.

## Thresholds
- No peer-reviewed absolute thresholds for per-document sentence-length CV, nominalisation rate, etc. found. Everything published is distributional/classifier-based. Any "CV < 0.4 = AI" number = folklore.
- Recommendation: build a reference distribution per language from human-written motivation letters (genre matters most, 2604.14111), and gate on z-score / percentile (e.g., fail if below human 10th percentile on ≥2 of: sentence-length SD, MTLD, share of sentences <8 words; above human 90th percentile on nominalisation rate or stock-phrase hits).
- 800 words ≈ 35–45 sentences: SD estimate noisy; don't gate on one feature.

## Tools & language coverage
- spaCy official trained pipelines (spacy.io/models, fetched 2026-09-28) [OD]: 24 langs incl. English, German, French, Russian; NOT Turkish, NOT Azerbaijani.
- TextDescriptives (hlasse.github.io/TextDescriptives, JOSS/arXiv 2301.02057) [OD]: spaCy-based: descriptive stats (sentence length mean/median/SD), readability, dependency distance, POS proportions, quality, coherence, information theory. Readability formulas are English-calibrated (syllables) [practitioner] → use only descriptive stats cross-lingually.
- LexicalRichness (lexicalrichness.readthedocs.io) [OD]: MTLD, HD-D, TTR variants; tokenizer-agnostic (pass your own tokens) → works for any language with a tokenizer; for agglutinative Turkish/Azerbaijani compute on LEMMAS or the numbers are not comparable to English.
- Stanza: 80 languages via UD [OD]; Turkish via UD (IMST, BOUN…). Azerbaijani official coverage unclear from fetch.
- TurkicNLP arXiv 2602.19174v3 (2026-03-16) [preprint, Apache-2.0, `pip install turkicnlp[stanza]`]: Turkish + Azerbaijani tokenization, sentence split, lemma, POS, morphology (Apertium FST), dep parse. Azerbaijani 87.0 UPOS / 64.6 LAS; Turkish 86.9 / 70.1 (Glot500 on Parallel Turkic UD). → Enough for POS-rate features (nominalisation via suffix/morph features like -lik/-ma/-ış), not for fine syntax.
- Nominalisation in code: English suffix list (-tion,-ment,-ness,-ity,-ance/-ence) on NOUN POS; German -ung/-heit/-keit/-ion; French -tion/-ment/-ité/-ance; Russian -ние/-ство/-ость/-ция; Turkish/Azerbaijani -lik/-lık/-luk/-lük, -ma/-me (verbal noun), -ış/-iş/-uş/-üş via morph features. Participial clauses via dependency labels (acl/advcl with VerbForm=Part/Ger/Conv) where parser exists.
# F. TypeSafe Jev — notes (fetched 2026-09-28)

Tier key: [OD] official docs, [PR] practitioner, [F] folklore/SEO

## Versions / limits / price
- docs.typesafe.ai/models.md [OD]: current model jev-1.13.0, aliases jev-latest, jev-preview. No newer version documented as of 2026-09-28.
  Input $0.042/M tokens, output free. Rate limit 250k tok/s, 1,200 req/min. Context: 64k total (state + all questions), 32k for state + single longest question. English primary; "other languages including CJK supported but with lower accuracy". No fine-tuning.
- openrouter.ai/blog/insights/what-is-jev/ (2026-09-21) [OD-ish, vendor blog]: slugs typesafe/jev-1.13 and ~typesafe/jev-latest; OpenRouter lists 32k context. Probabilities vary between calls on identical input. Cannot do arithmetic, date math, threshold comparisons.
  (openrouter.ai/typesafe/jev-1.13 model page returned 404 to fetch on 2026-09-28.)
- docs.typesafe.ai/api.md [OD]: Choice ≤255 options; Score 2–10 levels; questions/request not specified. Recommended model "jev-latest" (NB: for us, pin jev-1.13 for reproducibility).
- how-to-build-with-system-one.md [OD]: "Most queries complete in about 100 ms".

## Primitives
- Noul: P(yes) 0–1, no separate confidence. Optional criteria {true,false}. [OD primitives/noul.md]
  Do: one condition per Noul; phrase so high = yes; statements work too; add criteria when boundary subtle.
  Don't: invert ("Is message free of personal data?" ✗); combine conditions ("angry AND refund" ✗).
  Middle values = uncertainty, not "medium degree". Example thresholds YES 0.8 / NO 0.2, middle 0.2–0.8 to review.
- Choice: returns choice, probabilities, confidence; confidence = concentration, e.g. 3 options: (3·pmax−1)/2. [OD confidence.md] Recommend "other/none" option [PR gist].
- Score: ordered levels 2–10.
- Structured instructions/criteria accept JSON; criteria entries can carry `examples` arrays; `inspect` names a state field to focus on. [OD primitives/advanced.md]
- Reference nested state with backticked dot paths `ticket.messages[0].text`. [OD primitives.md]
- "Ask for a judgment a knowledgeable person makes in a second." [OD primitives.md]

## Jaggedness jev-1.13 [OD docs.typesafe.ai/model-jaggedness/jev-1.13.md]
1 literal reading; 2 math/counting; 3 numeric reps; 4 score interpolation; 5 date comparison;
6 indirection/double negatives/multi-hop; 7 large irrelevant state = distractor → filter in code;
8 adversarial content — does not treat state as hostile, injected instructions can steer;
9 contradictory instructions vs criteria; 10 NO guarantee P(noul) = 1 − P(not noul) across separate questions → don't transfer thresholds between primitives/wordings; 11 not a generator.

## Calibration / thresholds
- Claimed calibrated (RLCD). "0.8 means right ~80% of the time on that kind of answer" (OpenRouter blog).
- confidence.md: >0.9 for high-stakes auto; <0.5 to human; "no universal threshold; test on your data".
- consistency_noul_cookbook [OD]: 14-question rubric ×15 runs; mean per-question prob SD 0.0102 (lower than LLM baselines); band <0.30 no, >0.70 yes, 0.30–0.70 human.
- citation_check cookbook [OD]: string-match quote first (fabricated if absent, no model call), then ONE Choice {supports, contradicts, says_nothing}; ≥0.8 confidence auto-accept. Only n=8 test.

## Third-party
- Langfuse blog 2026-09-18 [PR]: Good Start Labs 6,003 rubric checks, Jev agreed with Claude Fable 5.1 91.5% at $160/M graded answers; DeepSeek V4.1 Flash 93.5% at $260/M. Failure modes: cannot abstain (forced pick), no rationale, context rot; notes docs 64k/32k vs OpenRouter 32k.
- gist pjburnhill 2026-09-16 [PR, unofficial].

## Against the pipeline assumptions
- Atomic questions: CONFIRMED by docs (one condition per Noul, decompose).
- Three wordings for redundancy: NOT recommended by docs; jaggedness #10 says wordings are not structurally consistent → average of three wordings is fine as an ensemble but each wording needs its own threshold; do not share a bar across wordings. Docs' own consistency evidence is about repeated identical calls (SD 0.01), which means repeating the SAME wording buys ~nothing; varying wording is the only redundancy that adds information. Docs never measure multi-wording gains.
- Bars 0.35–0.9: docs' examples use 0.2/0.8, 0.3/0.7, 0.8 (Choice confidence), >0.9 high-stakes. A 0.35 bar is inside every documented "route to review" band — treat 0.35–0.65 as uncertain, not as pass/fail, unless calibrated on your own labels.
- "Does this claim more than the facts support?" = negatively framed but high=yes (bad thing) — OK per docs (high means yes). Avoid "Is this sentence free of unsupported claims?".
- Non-English letters: lower accuracy stated. Turkish/Azerbaijani/Russian verification needs own calibration set; consider checking an English gloss? (risk: translation error).
- Adversarial: letter text is model-generated, low risk; but programme page text in state is third-party → jaggedness #8.
# G. Evaluation harness — notes (fetched 2026-09-28)

## Judges
- "Who Judges Matters: Family-Conditioned Preference in LLM-as-Judge Panels" arXiv 2609.17857 (2026-09-15) [preprint]: Llama 3.1, Qwen 2.5, Gemma 2, Yi 1.5, 9,312 pairwise judgments. Same-family lift 3.4–8.4 pp for all four families (even though no judge judged its own outputs). 55.4% of AB/BA pairs REVERSE on swap. Panel composition changes 18.5% of pairwise outcomes vs family-balanced reference. Naive per-family statistic confounded with quality (r=0.95).
  → Never judge Chinese-model letters with a Chinese-family judge only; swap order and count inconsistent pairs as ties.
- "Judging the Judges: Position Bias in LLM-as-a-Judge", IJCNLP-AACL 2025 [peer-reviewed] aclanthology 2025.ijcnlp-long.18: 15 judges, 150k instances; position bias not random, varies by judge/task, strongest when quality gap is small.
- "Am I More Pointwise or Pairwise? Position Bias in Rubric-Based LLM-as-a-Judge" arXiv 2602.02219 (2026) [preprint]: order of rubric options shifts scores; randomise option order, multiple passes.
- Zheng et al. MT-Bench, NeurIPS 2023 [peer-reviewed] arXiv 2306.05685: position, verbosity, self-enhancement biases; swap mitigation.
- Panickssery et al. NeurIPS 2024 arXiv 2404.13076 [peer-reviewed]: LLM evaluators recognise and favour own generations.

## Admissions-specific
- Isley, Gaebler, Goel "AI-written admissions essays are widespread but penalized" arXiv 2609.22549 (2026-09-18) [preprint, Harvard/NYU]: 7,462 applications to a US public-policy master's, 2020–2025. By 2025 56% (69.3% of international applicants) submitted predominantly AI-written essays (GPTZero 3.9 high-confidence; FPR <1% pre-ChatGPT). Each AI-flagged essay −1.5 pp admission probability controlling for 400+ covariates. Admissions officers detected AI with AUC 0.70, and essays perceived as AI got lower quality ratings even after adjusting for measured quality. AI improved mechanics (grammar, clarity, stylistic consistency) most; substantive dimensions (voice, commitment) least.
  → The penalty is on perceived AI-ness; "polish" is the signal. Target = specific, concrete, personal content with human-range stylistic variation, not smoother prose. Also: an off-the-shelf detector (GPTZero) is effectively the reader's proxy → worth using a detector score as ONE canary metric (not a gate we optimise to zero — Goodhart).
- "The Digital Divide in Generative AI … College Admissions Essays", ACM L@S 2026 doi 10.1145/3774398.3811620 / arXiv 2602.17791 [peer-reviewed]: LLM use rose sharply 2024, more among lower-SES applicants.
- arXiv 2410.17439 "AI-generated Essays: Characteristics and Implications on Automated Scoring" [preprint]: LLM scorers rate GPT text more favourably than human → an LLM judge will over-reward our own AI prose; must be anchored to human-labelled pairs.
- ScienceDirect 2026 S2666920X26000275 [peer-reviewed]: weak intra-model stability, low alignment with human raters for LLM essay scoring.

## Golden sets / gates / canaries (practitioner tier)
- Langfuse "Golden dataset evaluation" langfuse.com/resources/engineering/golden-dataset-evaluation [PR/vendor].
- futureagi.com 2026 checklist [PR/vendor]: 50–200 examples per route for CI gates; pin hardest 10% of historical failures as immutable; 80–90% recent production; refresh weekly; sample 5–10% of live traffic for online scoring. Vendor blog → folklore-to-practitioner.
- Recommendation for us: canary = deterministic checks on 100% (free), Jev on 100% (≈$0.0001/letter), LLM pairwise judge on a stratified 2–5% sample + every letter that needed repair.

## Rubric design
- Atomic yes/no rubric items outperform holistic scores (consistent with TypeSafe docs + 2602.02219 finding on option order).
- Cost/agreement: Langfuse 2026-09-18 blog: Jev 91.5% agreement with Claude Fable 5.1 at $160/M graded answers.
