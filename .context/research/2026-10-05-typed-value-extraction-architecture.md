# Typed value extraction from short multilingual funding lines: which architecture (A–F)

Date: 2026-10-05. Serves: the owner's choice of extraction step for the funding card reader
(money, dates and roles, places/nationalities, degree levels, entry requirements; az, tr, ru, en,
ko, zh, fr, de, hu; lines of 5–80 words, often a table row with its header).

Builds on, and does not repeat:
- `/home/orkhan/Desktop/elmify-design/.context/research/2026-10-03-reliable-extraction-engine.md`
  (threshold certification, 299 clean accepted items per stratum for 1% at 95%, correlated reader
  errors, key-error floor). Everything below about "precision" inherits that note's caveats.
- `/home/orkhan/Desktop/elmify-design/.context/research/2026-10-03-dates-and-bounds-fixes.md`
  (improved date finder 208/211 key dates; `dateparser` rejected; ranges and approximations are
  code's job, not Jev's).
- `/home/orkhan/agent-workspace/second-reader-findings.md` (internal measurement: on 100
  Jev-uncertain facts, Sonnet 5.5 87 right, NuExtract3 local 43, Jev alone 48; specialised
  extractors "reviewed and rejected").

## Answer first: ranked recommendation

1. **C, built narrowly: union of today's code finders and LLM-proposed exact quotes, a byte-exact
   substring gate, the same code parsers, then the existing classifier / second reader for roles.**
   The LLM writes a quote only as a pointer; the stored value is always the source substring that
   code located and parsed, so the "no generative model writes card text" rule still holds.
   Do not adopt LangExtract as the library for this (reasons in section 4); the grounding step is
   a substring search you already own.
2. **A alone (improve finders)** stays the precision anchor for formatted values, but its recall is
   capped by the finder, and the gap you measured (money 15/42, nationality 31/64) is the long tail
   that rules chase forever. Keep A inside C; do not rely on it alone.
3. **F (constrained / JSON-schema decoding)** as a format guard on the LLM step only. It controls
   shape, not truth; the hallucination control is the substring gate.
4. **E (temporal taggers)**: no adoption. Coverage for az/tr is automatic-resource quality only,
   and event-anchored relative dates ("15 months before the start of the grant") are not a date
   any tagger can resolve. Store them as offset + direction + anchor text in code.
5. **D (GLiNER / NuExtract / UIE)**: keep the earlier rejection. Published multilingual zero-shot
   numbers are far below what a card needs, and your own harness already measured NuExtract3 at
   about half of Sonnet's score.
6. **B alone**: worse than C. It throws away the deterministic finders, which are the most precise
   source for well-formatted dates and amounts, and the evidence below shows LLM-only extraction
   loses to hybrids.

**What would change this:** if the LLM step's measured unique recall (correct values found by B
and not by A) on the 1,400 lines is small, C collapses to A and the LLM step is not worth its
cost. That is the first number to measure (section 7).

## 1. Scope (sub-questions answered)

1. Do measured studies show a union or cascade of rules and LLM beating either alone? (section 2)
2. How often do LLM "quotes" fail to be verbatim, and what does a verbatim check remove and not
   remove? (section 3)
3. What does LangExtract actually do (grounding, offsets, defaults), its license and any
   evaluation? (section 4)
4. Measured multilingual numbers for GLiNER / NuExtract / UIE-family, esp. tr, ru, az. (section 5)
5. Temporal taggers: language coverage (az, tr) and relative-date normalisation. (section 6)
6. Constrained decoding as hallucination control. (section 3)
7. Cost of measuring on the 1,400 lines. (section 7)

## 2. Hybrid rules + LLM beats either alone (measured, but not in this domain)

- Cascade, clinical reports: regex first, an 8B LLM only "when regex failed or returned ambiguous
  results"[^19]; "In CPET reports, the hybrid approach improved F1-score from 0.74 (regex alone) to
  0.98".[^20] This is a cascade (LLM fills regex misses), which is exactly the recall gap here.
- Union by responsibility, PII in crash narratives: "The Hybrid Extractor routes structured PII (e.g.,
  phone numbers and email addresses) to a rule-based model (i.e., Presidio)"[^21] and context-dependent
  PII to a fine-tuned LLM, with an ensemble and a verifier; result "a precision of 0.82, a recall of
  0.94".[^22]
- Generate-then-verify, clinical schema extraction (193 fields): F1 0.66 "by balancing high recall
  from generative models with high precision from verification".[^23] **Unverified** (in the paper
  body, PDF only, not quotable here): transcript verification moved precision 0.51 -> 0.59 at a
  recall cost of 0.73 -> 0.70.
- **Unverified** (abstract seen only through an Exa library page, not fetched): a prostate-cancer
  study where the hybrid of expert regex + LLM beat regex alone, LLM alone and regex-prefilter + LLM
  on all three attributes.
- Limits: all of these are clinical/English or Dutch documents, not multilingual web lines; none
  reports a per-language breakdown. The direction (hybrid > either alone; verification buys
  precision for a small recall cost) is consistent across them; the magnitudes do not transfer.

## 3. Verbatim quotes, hallucination, and what a substring check does and does not fix

- **LLM quotes are often not verbatim.** On QA with quoting, "existing hybrid methods frequently
  hallucinate quoted spans, with exact extraction accuracy dropping below 40% in technical
  domains"[^24]; constraining decoding to context spans "achieves near-perfect extraction faithfulness
  regardless of the model used".[^25] Consequence for C: a post-hoc exact-substring gate gives the
  same faithfulness guarantee as constrained decoding (derived: a span either is or is not a
  substring), but every non-verbatim quote is a recall loss you must count, not ignore.
- **Small extractive models can beat LLM extractors on span selection** in one benchmark: "a
  150M-parameter ModernBERT token classifier ... achieves the best word-level F1 (53.6), ahead of
  the strongest evaluated LLM extractor (48.7)"[^26] (English research papers, word-level overlap;
  not typed values).
- **The hallucination that matters for NER-style extraction is over-labelling, not invention.**
  GPT-NER reports that "LLMs have a strong inclination to over-confidently label NULL inputs as
  entities"[^27] and fixes it with a second pass "prompting LLMs to ask itself whether the extracted
  entities belong to a labeled entity tag".[^28] That second pass is the same job your classifier
  does in A and C.
- **What the substring gate cannot catch (derived, and already visible in your data):** a value
  that is on the line but has the wrong role or wrong attribute. Examples from the 2026-10-03 dates
  note: the grade minimum "minimum 71 bal" read as money, the second date of a range given the wrong
  role. In the internal second-reader run, Jev's sub-bar date roles were right 8/19 and Sonnet's
  19/19; all of those values were verbatim. So the gate controls fabrication; role precision still
  comes from the classifier + second reader + calibrated threshold (reliable-extraction note).
- **F, constrained decoding:** grammar constraints help structured NLP tasks: "grammar-constrained
  LMs substantially outperform unconstrained LMs or even beat task-specific finetuned models"[^30],
  but format restrictions can cost reasoning: "we observe a significant decline in LLMs reasoning
  abilities under format restrictions".[^29] Use a schema for the proposer's output shape (quote,
  type), keep the role decision in the classifier, and do not count schema compliance as a
  hallucination control.

## 4. LangExtract (option B's named example): what it does

- Claims: "Maps every extraction to its exact location in the source text, enabling visual
  highlighting for easy traceability and verification"[^1]; ungrounded output is flagged:
  "extractions that cannot be located in the source text will have char_interval = None".[^2]
  Structured output relies on "controlled generation in supported models like Gemini"[^43]; long
  documents use chunking and "multiple passes for higher recall".[^44]
- License and status: "Use is subject to the Apache 2.0 License"[^3]; "This is not an officially
  supported Google product."[^4]
- **The grounding is not strict by default** (from source, `langextract/resolver.py`):
  - "Uses exact matching first (difflib), then fuzzy alignment fallback if enabled."[^5] and the
    fuzzy threshold is "Minimum fraction of extraction tokens that must be matched (0-1). Default
    0.75."[^6] A fuzzy hit is labelled "MATCH_FUZZY: Best overlap window meets threshold".[^7]
  - Partial matches are accepted by default: "accept_match_lesser: Whether to accept partial exact
    matches".[^8]
  - Tokens are compared lowercased: "Extract and lowercase tokens from the input text into
    words."[^9], with "Lowercases and applies light pluralisation stemming."[^10] for fuzzy matching.
  - **Consequence (derived):** with defaults, a model quote "1 500 euros per month" against a source
    "1 200 euros per month" matches 4 of 5 tokens (0.8 >= 0.75) and is returned as grounded with an
    offset. For money and dates that is a wrong value with a valid-looking provenance. If used at
    all: `enable_fuzzy_alignment=False`, `accept_match_lesser=False`, keep `MATCH_EXACT` only, and
    copy `text[start:end]` from the source, never `extraction_text`.
- **Published evaluation:** none found. The README offers examples and a demo, no precision/recall
  numbers. **Unverified:** how its tokenizer segments Korean and Chinese (no spaces), which decides
  whether exact alignment works there at all.
- **Why not adopt it here (derived):** its value-adds are long-document chunking, multi-pass recall
  and an HTML viewer; your inputs are single 5–80-word lines. The part you need is one prompt and a
  byte-exact `str.find` with an occurrence count, which is less code than configuring LangExtract
  away from its defaults.

## 5. Specialised extractors (D): measured numbers

- **GLiNER, zero-shot, MultiCoNER (11 languages):** the paper states "our model surpasses ChatGPT in
  8 of 10 languages"[^11], but also "As expected, the supervised baseline demonstrated superior
  performance, significantly outperforming the zero-shot models."[^12] Turkish row (supervised XLM-R,
  ChatGPT, GLiNER-En, GLiNER-Multi): 46.8 / 31.9 / 22.0 / 30.0 F1.[^13] On non-Latin scripts the English
  backbone collapses, "particularly in Bengali, where it scored only 0.89 in the F1 score".[^14]
  These are entity F1s near 30 for tr/ru/ko/zh, against 2023 ChatGPT, on generic entity types, not
  scholarship amounts. Nothing here supports card-grade precision.
- **GLiNER2:** "GLiNER2 maintains CPU efficiency and compact size while introducing multi-task
  composition through an intuitive schema-based interface."[^15] The abstract reports "competitive
  performance"; no multilingual numbers were found.
- **NuExtract 1.5:** "several languages (English, French, Spanish, German, Portuguese, and
  Italian)"[^16], so az, tr, ru, ko, zh and hu are outside its stated coverage. It is "trained to
  prioritize pure extraction, so in most cases all text generated by the model is present as is in
  the original text"[^17] ("most cases": you still need the substring gate).
- **NuExtract 2.0 (vendor benchmark, marked as such):** "NuExtract 2.0 PRO largely outperforms frontier
  models, with a +9 F-Score margin over GPT-4.1."[^18] Benchmark is NuMind's own; the 4B open model is
  "research license".[^31] Your harness measured NuExtract3 Q8 local at 43/100 vs Sonnet 87/100 on
  your own uncertain facts (internal file above), which outranks the vendor claim for this decision.
- **Azerbaijani, the hardest language here:** a community fine-tuned BERT NER (model card, not
  peer-reviewed) reports per-class "MONEY 0.62 0.57 0.59 532"[^32] and "DATE 0.49 0.48 0.49 844"[^33]
  (precision, recall, F1, support). Supervised az NER is weak exactly on the value types the card
  needs.
- **UIE family:** in GLiNER's zero-shot table InstructUIE (11B) averages 47.2 vs GLiNER-L 60.9 on
  English OOD NER (same page as [^11]); no multilingual UIE result was fetched. **Unverified** beyond that.
- **Verdict:** D adds a CPU-cheap candidate source at best; there is no measured evidence it would
  add candidates an LLM proposer misses, and the prior rejection stands.

## 6. Temporal taggers (E) and relative dates

- **HeidelTime:** "HeidelTime contains automatically created resources for 200+ languages in addition
  to manually created ones for 13 languages."[^34] Hand-made: "English, German, Dutch, Vietnamese,
  Arabic, Spanish, Italian, French, Chinese, Russian, Croatian, Estonian and Portuguese"[^35]; the
  automatic ones "are of lower quality than the manually created ones".[^36] Turkish and Azerbaijani
  exist only as automatic resources: the GitHub API lists `resources/auto-turkish` and
  `resources/auto-azeri` (checked 2026-10-05 at
  `https://api.github.com/repos/HeidelTime/heideltime/contents/resources/auto-turkish` and
  `.../auto-azeri`; a directory listing has no quotable sentence, so no footnote). Korean and
  Hungarian were not checked.
- **How bad automatic resources are, measured:** "the rule quality typically does not match the high
  accuracy of hand-crafted rules"[^37]; "HeidelTime with automatically created rules has a poor
  performance for some low-resource languages (el, ro, ua)".[^38] In that paper's Table 1 the
  HeidelTime-auto languages average 17.3 value F1 (same page). The neural replacement improves
  low-resource normalisation "up to 33 F1 on average"[^39] but was tested on Indo-European languages:
  "Our experiments are focused on Indo-European languages due to the lack of publicly available,
  labeled"[^40] data. No Turkish or Azerbaijani evaluation exists in it.
- **Anchoring must be separate:** directly predicting the anchored value fails, "current transformers
  are not able to correctly incorporate this information in a combined normalizing+anchoring
  step".[^41] That supports the current design: code finds the span, code anchors.
- **Duckling:** "Duckling supports many languages, but most don't support all dimensions yet"[^42];
  it has Turkish time rules ("module Duckling.Time.TR.Rules ( rules ) where"[^45]) including duration
  offsets ("ruleDurationBeforeTime :: Rule ruleDurationBeforeTime = Rule"[^46]); its `Duckling/Time`
  directory (GitHub API, same date) has TR, RU, KO, ZH, DE, FR, HU, EN and no AZ. "Duckling is
  BSD-licensed".[^47] Haskell server; anchoring is to a reference time, not to an event.
- **SUTime:** "The rule set that we distribute supports only English, but other people have developed
  rule sets for other languages, such as Swedish".[^48]
- **Event-anchored relative dates (derived, no source):** "15 months before the start of the grant",
  "2 weeks after results" have an event as anchor, not a calendar date. No tagger above can
  normalise them without knowing the event's date. Store `{offset: P15M, direction: before, anchor:
  "start of the grant" (verbatim)}` and resolve only when the anchor event's date is itself on the
  card. A regex per language for "<number> <unit> before/after/until" plus the LLM proposer's quotes
  covers detection; the tagger adds nothing here.
- **Unverified:** a 2024 paper (Castro et al., "Generative LLMs for Multilingual Temporal Expression
  Normalization") reports fine-tuned 7B LLMs beating rule systems on 7 European languages; seen only
  as a search snippet.

## 7. What to measure on the 1,400 lines, and the cost

Arms, all scored against the same key, per value type and per language:
- **A:** current finders (with the 2026-10-03 date and range fixes).
- **B:** an LLM proposer per line (line + its table header): returns `{type, quote}` only, under a
  JSON schema; code keeps a quote only if it is a byte-exact substring of the line, records the
  occurrence count, and parses it with the same parsers as A.
- **C = A ∪ B**, deduplicated by character span.

Numbers to report:
1. **Candidate recall** per type (the 15/42, 31/64, 35/53, 140/169 baselines) for A, B, C.
2. **Unique contribution:** correct values found only by B, only by A. This decides C vs A.
3. **Verbatim-fail rate** of B's quotes, and how many failed quotes were real values (recall lost
   to the gate; [^24] says this can be large).
4. **Parse-fail rate** on B's verbatim quotes (a quote that is verbatim but the parser cannot read).
5. **End-to-end precision at the classifier's bar** for C vs A, using the reliable-extraction
   note's exact binomial bound. With only 42 money lines, expect to show a recall difference, not to
   certify precision.
6. **Hand audit:** 50 B-only candidates the key calls wrong, and 50 lines where every arm finds
   nothing. The key is model-built; a B-only find the key lacks may be a key miss (2026-10-03 note:
   key errors exist). Use a proposer from a family not in the key (the key used DeepSeek Flash, GPT
   Luna and Sol), e.g. Sonnet 5.5 or GLM; a DeepSeek proposer would flatter itself.

Cost (derived arithmetic, not measured): assume about 1,000–1,500 input tokens per line (instructions,
a few examples, header, line) and about 100 output tokens.
- 1,400 lines -> about 2.1M input and 0.14M output tokens per run.
- DeepSeek V4.1 Flash, cache-miss peak prices "1M INPUT TOKENS (CACHE MISS) OFF-PEAK $0.15 $0.66 PEAK
  $0.3 $1.32"[^49] and "1M OUTPUT TOKENS OFF-PEAK $0.6 $1.98 PEAK $1.2 $3.96"[^50] (first column is
  Flash): about 2.1 x 0.30 + 0.14 x 1.2 = **about $0.80 per run**.
- Sonnet 5.5 at $2 / $10 per M (internal second-reader file; not re-fetched): about 4.2 + 1.4 =
  **about $5.6 per run**.
- Three runs per proposer to see sampling variance, two proposers: **under $25**, plus a few hours
  of hand audit. Latency was not measured anywhere in the sources; **Unverified**.

Production cost of C (derived): one proposer call per line on lines A's finders do not already
resolve with confidence; at Flash prices that is cents per page, well inside the owner's $100 per
student budget (internal file).

## Search log and tools

- The option list (A–F) came from the task, not from discovery. Exa searches found the evidence:
  "hallucination in LLM extraction / verbatim span check" (CHyD, ACL-Verbatim), "rule + LLM hybrid
  with precision/recall" (cardiology cascade, crash-PII workflow, MEDIQA-SYNUR), "GLiNER / NuExtract
  benchmarks", "LLM temporal normalisation vs HeidelTime" (Lange et al.), "Azerbaijani / Turkish NER
  with LLMs". Owner pages (GitHub repos, raw source, Hugging Face cards, arXiv, ACL Anthology, Europe
  PMC, DeepSeek docs) were then fetched directly with scrapling `get` / `bulk_get`.
- Not used: Brave, Tavily, Context7. PubMed's page returned an empty abstract to scrapling, so the
  cardiology study is cited through Europe PMC's API record of the same PMID. The MEDIQA PDF returned
  binary text and is cited by its Anthology landing page.

## Open questions

- How large is B's unique recall on these lines? No published study covers multilingual scholarship
  pages; only the measurement in section 7 settles it.
- Does an exact-substring gate drop many correct Korean/Chinese values because the proposer
  normalises full-width digits, spaces in "1 200" or "만원" units? Measure the verbatim-fail rate per
  language before trusting C's recall.
- Korean and Hungarian HeidelTime automatic resources were not checked (irrelevant if E is rejected).
- LangExtract's CJK tokenisation and any published evaluation: none found.
- Latency per line for any arm: not reported in any fetched source.

## Sources

[^1]: https://github.com/google/langextract "Maps every extraction to its exact location in the source text, enabling visual highlighting for easy traceability and verification."
[^2]: https://github.com/google/langextract "extractions that cannot be located in the source text will have char_interval = None"
[^3]: https://github.com/google/langextract "Use is subject to the Apache 2.0 License"
[^4]: https://github.com/google/langextract "This is not an officially supported Google product."
[^5]: https://raw.githubusercontent.com/google/langextract/main/langextract/resolver.py "Uses exact matching first (difflib), then fuzzy alignment fallback if enabled."
[^6]: https://raw.githubusercontent.com/google/langextract/main/langextract/resolver.py "Minimum fraction of extraction tokens that must be matched (0-1). Default 0.75."
[^7]: https://raw.githubusercontent.com/google/langextract/main/langextract/resolver.py "MATCH_FUZZY: Best overlap window meets threshold"
[^8]: https://raw.githubusercontent.com/google/langextract/main/langextract/resolver.py "accept_match_lesser: Whether to accept partial exact matches"
[^9]: https://raw.githubusercontent.com/google/langextract/main/langextract/resolver.py "Extract and lowercase tokens from the input text into words."
[^10]: https://raw.githubusercontent.com/google/langextract/main/langextract/resolver.py "Lowercases and applies light pluralisation stemming."
[^11]: https://arxiv.org/html/2311.08526v1 "our model surpasses ChatGPT in 8 of 10 languages"
[^12]: https://arxiv.org/html/2311.08526v1 "As expected, the supervised baseline demonstrated superior performance, significantly outperforming the zero-shot models."
[^13]: https://arxiv.org/html/2311.08526v1 "Turkish 46.8 31.9 22.0 30.0"
[^14]: https://arxiv.org/html/2311.08526v1 "particularly in Bengali, where it scored only 0.89 in the F1 score"
[^15]: https://aclanthology.org/2025.emnlp-demos.10/ "GLiNER2 maintains CPU efficiency and compact size while introducing multi-task composition through an intuitive schema-based interface."
[^16]: https://huggingface.co/numind/NuExtract-1.5 "several languages (English, French, Spanish, German, Portuguese, and Italian)"
[^17]: https://huggingface.co/numind/NuExtract-1.5 "trained to prioritize pure extraction, so in most cases all text generated by the model is present as is in the original text"
[^18]: https://about.nuextract.ai/blog/outclassing-frontier-llms-nuextract-2-0 "NuExtract 2.0 PRO largely outperforms frontier models, with a +9 F-Score margin over GPT-4.1."
[^19]: https://www.ebi.ac.uk/europepmc/webservices/rest/search?query=EXT_ID:41646749%20AND%20SRC:MED&resultType=core&format=json "regex rules were applied first, followed by targeted prompting of an on-premises Llama-3.1-8B-Instruct LLM only when regex failed or returned ambiguous results"
[^20]: https://www.ebi.ac.uk/europepmc/webservices/rest/search?query=EXT_ID:41646749%20AND%20SRC:MED&resultType=core&format=json "In CPET reports, the hybrid approach improved F1-score from 0.74 (regex alone) to 0.98"
[^21]: https://arxiv.org/abs/2604.15369 "The Hybrid Extractor routes structured PII (e.g., phone numbers and email addresses) to a rule-based model (i.e., Presidio)"
[^22]: https://arxiv.org/abs/2604.15369 "the agentic workflow achieves strong performance with a precision of 0.82, a recall of 0.94"
[^23]: https://aclanthology.org/2026.clinicalnlp-1.25/ "by balancing high recall from generative models with high precision from verification"
[^24]: https://arxiv.org/abs/2609.10046 "existing hybrid methods frequently hallucinate quoted spans, with exact extraction accuracy dropping below 40% in technical domains"
[^25]: https://arxiv.org/abs/2609.10046 "our approach achieves near-perfect extraction faithfulness regardless of the model used"
[^26]: https://arxiv.org/abs/2605.21102 "achieves the best word-level F1 (53.6), ahead of the strongest evaluated LLM extractor (48.7)"
[^27]: https://arxiv.org/abs/2304.10428 "LLMs have a strong inclination to over-confidently label NULL inputs as entities"
[^28]: https://arxiv.org/abs/2304.10428 "prompting LLMs to ask itself whether the extracted entities belong to a labeled entity tag"
[^29]: https://arxiv.org/abs/2408.02442 "we observe a significant decline in LLMs reasoning abilities under format restrictions"
[^30]: https://arxiv.org/abs/2305.13971 "grammar-constrained LMs substantially outperform unconstrained LMs or even beat task-specific finetuned models"
[^31]: https://about.nuextract.ai/blog/outclassing-frontier-llms-nuextract-2-0 "NuExtract 2.0 4B (Qwen 2.5 VL 3B base, research license)"
[^32]: https://huggingface.co/ismatsamadov/azeri-turkish-bert-ner "MONEY 0.62 0.57 0.59 532"
[^33]: https://huggingface.co/ismatsamadov/azeri-turkish-bert-ner "DATE 0.49 0.48 0.49 844"
[^34]: https://github.com/HeidelTime/heideltime "HeidelTime contains automatically created resources for 200+ languages in addition to manually created ones for 13 languages."
[^35]: https://github.com/HeidelTime/heideltime "English, German, Dutch, Vietnamese, Arabic, Spanish, Italian, French, Chinese, Russian, Croatian, Estonian and Portuguese"
[^36]: https://github.com/HeidelTime/heideltime "Although these resources are of lower quality than the manually created ones"
[^37]: https://ar5iv.labs.arxiv.org/html/2205.10399 "the rule quality typically does not match the high accuracy of hand-crafted rules"
[^38]: https://ar5iv.labs.arxiv.org/html/2205.10399 "Note that HeidelTime with automatically created rules has a poor performance for some low-resource languages (el, ro, ua)."
[^39]: https://arxiv.org/abs/2205.10399 "performance improvements of up to 33 F1 on average compared to the state of the art"
[^40]: https://ar5iv.labs.arxiv.org/html/2205.10399 "Our experiments are focused on Indo-European languages due to the lack of publicly available, labeled"
[^41]: https://ar5iv.labs.arxiv.org/html/2205.10399 "current transformers are not able to correctly incorporate this information in a combined normalizing+anchoring step"
[^42]: https://github.com/facebook/duckling "Duckling supports many languages, but most don't support all dimensions yet"
[^43]: https://github.com/google/langextract "leveraging controlled generation in supported models like Gemini to guarantee robust, structured results"
[^44]: https://github.com/google/langextract "parallel processing, and multiple passes for higher recall"
[^45]: https://raw.githubusercontent.com/facebook/duckling/main/Duckling/Time/TR/Rules.hs "module Duckling.Time.TR.Rules ( rules ) where"
[^46]: https://raw.githubusercontent.com/facebook/duckling/main/Duckling/Time/TR/Rules.hs "ruleDurationBeforeTime :: Rule ruleDurationBeforeTime = Rule"
[^47]: https://github.com/facebook/duckling "Duckling is BSD-licensed"
[^48]: https://nlp.stanford.edu/software/sutime.html "The rule set that we distribute supports only English, but other people have developed rule sets for other languages, such as Swedish"
[^49]: https://api-docs.deepseek.com/quick_start/pricing/ "1M INPUT TOKENS (CACHE MISS) OFF-PEAK $0.15 $0.66 PEAK $0.3 $1.32"
[^50]: https://api-docs.deepseek.com/quick_start/pricing/ "1M OUTPUT TOKENS OFF-PEAK $0.6 $1.98 PEAK $1.2 $3.96"
