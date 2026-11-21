# Turkish grammar checking and per-language stock-word lists (2026-10-14)

Scope: two facts for the motivation-letter writing-quality pass. Builds on, and does not repeat,
`~/agent-workspace/elmify-runs/motivation-letter/2026-10-12-human-admissions-writing-literature.md`
(English lists, Vale, proselint, LanguageTool, slop-guard).

## Answers first

**Q1. Turkish:** only **spelling** is cheaply available from Python. The cheapest option that works is
**zemberek-python**: Apache-2.0, pure Python with no JVM, and it checks spelling one word at a time using
morphology. Real grammar rules for Turkish exist in one place only: the **GECTurk** sequence tagger.
It covers 25 rules, is a BERT model with Apache-2.0 weights, needs torch, and was trained on synthetic
errors. **Azerbaijani: spelling only.** The options are a Hunspell dictionary (MPL-2.0) or a Go library.
No hosted grammar API for Turkish or Azerbaijani turned up.

**Q2.** For all four languages, the only measured per-language list is **tjuzek/ai-34-languages**. It
has German, French, Russian and Turkish, but no Azerbaijani. Each list ranks a language's whole
vocabulary and is released as CC0. The lists were measured on **news-sentence continuations by
GPT-4.1-mini**, not on letters, so they are a starting point to filter, not a ready-to-use stock-word
list. The searches found no other measured list for German, French, Russian or Turkish.

| Language | Best source | Size | How it was measured |
|---|---|---|---|
| German | ai-34-languages | full ranked vocabulary per language (paper tracks top 20, inspects top 200) | GPT-4.1-mini continuations vs the human second half of 100k WMT News Crawl sentences, log prevalence ratio |
| French | ai-34-languages | same | same |
| Russian | ai-34-languages | same | same |
| Turkish | ai-34-languages | same | same |
| Azerbaijani | none found | n/a | n/a |

## Sub-questions

1. Q1a: Can Zemberek or one of its Python ports check Turkish from Python without a JVM? If so, under
   what licence, how recently maintained, and is it spelling only?
2. Q1b: Is there any maintained Turkish checker that goes beyond spelling to real grammar rules?
3. Q1c: Does any of these cover Azerbaijani, and if not, what does?
4. Q2a: What does tjuzek/ai-34-languages actually contain (method, models, baseline, languages, size,
   licence), and can it serve as a stock-word list for letters?
5. Q2b: Is there any other measured list for German, French, Russian or Turkish?

## Q1. Turkish (and Azerbaijani) grammar and spelling from Python

| Tool | Licence | Last activity | What it checks | Python, no JVM? | Azerbaijani |
|---|---|---|---|---|---|
| Zemberek-NLP (Java) | Apache-2.0[^z1] | v0.17.1, July 2019[^z2]; "slow maintenance mode"[^z3]; last push 2026-10-04 (API) | word spelling and suggestions, plus normalisation of noisy text[^z4] | No. It is Java; its gRPC server[^z5] would be a JVM sidecar | No (Turkish only[^z6]) |
| zemberek-python (Loodos) | Apache-2.0[^zp1] | port of 0.17.1; last push 2025-06-23 (API) | spelling suggestions and normalisation, ported in part[^zp2] | **Yes**, pure Python[^zp3] | No |
| TDD hunspell-tr (dictionary) | MPL-2.0[^h1] | last push 2023-12-30 (API) | word spelling (Hunspell) | Needs a Hunspell binding (Unverified which one works best; `pip install hunspell` builds against the C library) | No |
| Starlang TurkishSpellChecker-Py (`nlptoolkit-spellchecker`) | GPL-3.0[^s1] | last push 2026-05-30 (API) | spelling, optionally ranked by an n-gram model[^s2] | Yes; needs Python 3.13 or later[^s3] | No |
| GECTurk sequence tagger | weights Apache-2.0[^g1]; GitHub repo has no licence file (API: `null`); web app CC BY-SA 4.0[^g2] | repo last push 2024-02-16 (API) | **grammar**: 25 expert-written rules[^g3] (for example de/da and *hiçbir* spacing), trained on synthetically generated errors[^g4] | Yes, but needs torch and transformers (a BERT model) | No |
| TurkicNLP | Apache-2.0; Apertium data is GPL-3.0 and downloaded separately[^t1] | last push 2026-10-11 (API) | no rule checker of its own; its `spellcheck=llm` backend sends text to an LLM[^t2] | Yes, Python 3.10 to 3.12[^t3] | Morphology yes; spelling only through the LLM backend[^t4] |
| Mozilla Azerbaijani Hunspell dictionary | MPL-2.0[^a1] | not checked | Azerbaijani word spelling[^a2] | Needs a Hunspell binding | **Yes** |
| az-lang-nlp (Go) | Apache-2.0 (README link; too short to quote) | not checked | Azerbaijani spelling (SymSpell plus morphology, 86K-entry dictionary[^a3]); a validator also checks punctuation and mixed scripts[^a4] | No. It is Go[^a5]; usable from Python over its gRPC stubs[^a6] | **Yes** |

The "(API)" dates come from the GitHub REST API (`api.github.com/repos/<owner>/<repo>`, field
`pushed_at`), read on 2026-10-14. That JSON cannot be quoted in the citation-check format, so these
dates have no footnote.

What each kind of tool can catch:
- **Zemberek and its port** check one word at a time against the morphology, so a well-formed word
  used wrongly passes. Its suggestions handle only one edit per word[^z7].
- **Accuracy:** on the trspell-10 benchmark, published by TDD in the hunspell-tr README (the authors
  of one of the tools compared), zemberek-python scores 96.99 error-detection F1 and 93.05 correction
  accuracy[^h2]. TDD hunspell-tr scores 98.58 and 94.67[^h3]. The README itself says hunspell-tr
  "performs much better in terms error correction accuracy"[^h4].
- **GECTurk** is the only checker with grammar rules. Its web app adds Zemberek-based spelling to the
  rule tagger[^g5], and the errors it handles include diacritics, compound words, pronouns and light
  verbs[^g6].
- **GPL-3.0 (Starlang):** running it on our own server is not "conveying" the program[^s4], so using it
  server-side does not trigger the copyleft obligations. It is still the only copyleft option here.

**Recommendation:** use zemberek-python for Turkish. It is the cheapest option that works (pure Python,
Apache-2.0), but it checks spelling only. Add the GECTurk tagger only if catching de/da-type grammar
errors is worth carrying a BERT model. For Azerbaijani, only spelling is available.

## Q2. Per-language stock-word lists

### tjuzek/ai-34-languages: what it actually contains

- **Method.** For each language the authors "compute Log Prevalence Ratio (LPR) metrics to identify
  words systematically overused by AI relative to human baselines"[^j1]. They split real news
  sentences in half, ask the model to continue the first half, and compare its continuation with the
  real second half[^j2].
- **Human baseline.** WMT News Crawl[^j3], from which they sample up to 100,000 sentences per
  language, all from 2020–2021[^j4]. That gives about 1.2M model tokens and 1.2M human tokens per
  language[^j5].
- **Models.**
  - Main lists: GPT-4.1-mini, prompted to act as a chat assistant[^j6].
  - Cross-checks only: Gemini 2.0 Flash and Claude 3 Haiku[^j7]. Haiku broadly agrees with GPT,
    "whereas Gemini is more distinct"[^j8].
  - The model writing Elmify's letters is none of these, so its own overused words will differ.
- **Languages.** 34 languages, German, French, Russian and Turkish among them[^j9]. Azerbaijani is
  not one of them (Kazakh and Kyrgyz are the only other Turkic languages in the study).
- **Size.**
  - Each language's file is a full ranked vocabulary: the data build keeps every row by default[^j10].
  - The paper analyses only the top 20 per language[^j11] and checks the top 200 by hand[^j12].
  - The data ships as a split 7z archive of CSV files[^j13]. It was not unpacked here, so row counts
    per language are **Unverified**.
- **Licence.** Word lists are CC0[^j14]; code is MIT-0[^j15]. The `lexa-index/README.md` licence
  section still reads "tbd" (two words, too short for a footnote). The top-level README is the
  licence owner and is the one to follow.
- **Shared overused verbs.** Verbs meaning "emphasise" appear in 24 of the 34 languages[^j16]. The
  paper's Table 2[^j17] lists them per language:
  - German: *betonen*, *hervorheben*
  - French: *insister*, *marquer*
  - Russian: *подчеркивать*
  - Turkish: *vurgula*

  The same table lists "importance" nouns for German (*Bedeutung*, *Notwendigkeit*, *Dringlichkeit*),
  French (*importance*, *nécessité*) and Russian (*важность*). The individual lemmas sit in table
  cells too short to quote.

**Is it usable as a stock-word list for letters? Partly, after filtering.**
- **Wrong kind of text.** The authors limit their results to "the web-news register represented in
  WMT News Crawl"[^j18]. Letters are a different kind of writing, so news-specific words will rank
  high without being stock words in a letter.
- **Topic noise.** The published Spanish top 10 is led by ordinary plural nouns (*testigos*,
  *organizaciones*, *estudios*). That reads as topic noise from the news text, not style (Unverified
  inference from Table 5 of the paper).
- **Usable style words.** The French top 10 does contain style words a letter would use: *captiver*,
  *habilement*, *poignant*, *palpable* (Table 6).
- **Practical use.** Take each language's top 200 content words and keep only the style words (by
  hand or with a model). Treat the result as a model-specific starting point, not a measured letter
  list.
- **Intended use.** The authors say the work "is not intended for AI detection"[^j19]. Using the
  lists to edit our own drafts does not conflict with that.

### Other measured lists (Q2b): none found

| Source | Language | Why it is not a list |
|---|---|---|
| DeHAT v1 (Zenodo, 2026) | German | A parallel corpus of human and model texts (16,519 text families[^d1]) built to support word-choice comparisons[^d2]. It could be used to derive a German list; it does not publish one. |
| Bergin & Atasoy 2026, IJRTT | Turkish | 147 ChatGPT-4o-mini texts against 147 texts by trainee teachers[^tr1]. Reports only aggregates: lexical diversity 6.9% vs 16.3%[^tr2], and the model used more idioms (1,038 vs 559) but fewer distinct ones (107 vs 205)[^tr3]. A list of the idioms is not in the abstract (Unverified whether the full text has one). |
| nauka-dialog.ru article (GPT-3, 160 texts) | Russian | Seen in an Exa result only, not fetched. Reports word frequencies and lexical diversity, not an overuse list (Unverified). |
| Shadrova & Richter, LCR 2026 abstract | German | Seen in an Exa result only, not fetched. Says LLMs overproduce words built on neo-Latin and neo-Greek stems; no list (Unverified). |

**Per-language result:**
- German, French, Russian, Turkish: best source is ai-34-languages, measured as described above.
- Azerbaijani: none found.

## How the candidates were found

- **Exa searches** (`web_search_exa`):
  - "Turkish spell checker or grammar checker library usable from Python". This produced Starlang,
    trspell, GECTurk WEB and google-research/turkish-morphology.
  - "TurkicNLP … Azerbaijani".
  - "Azerbaijani Hunspell dictionary or open-source Azerbaijani spell checker". This produced the
    Mozilla az dictionary, az-lang-nlp and the old aspell6-az.
  - Two searches for papers measuring LLM-overused words in German, French, Russian and Turkish.
    These produced DeHAT, the Turkish IJRTT study, the Russian article and the German LCR abstract.
- **Brave searches:** two keyword searches for LLM-overused-word papers. One returned nothing; the
  other surfaced only English studies.
- **Named by the caller:** Zemberek, zemberek-python, TurkicNLP and tjuzek/ai-34-languages.
- **Pages read:** every quoted page was fetched live with scrapling `get`. GitHub files were read
  as raw files. Repository metadata came from the GitHub REST API.
- **Tools missing or not used:**
  - PyPI pages return a bot challenge ("Client Challenge") to automated fetches, so no PyPI page is
    cited. Release versions on PyPI are therefore unconfirmed.
  - Tavily and Context7 were not needed.
  - The TurkicNLP README was read only up to its language table (about 62% of the file). The rest
    is the per-language component table.

## Sources

[^z1]: https://raw.githubusercontent.com/ahmetaa/zemberek-nlp/master/README.md "Code is licensed under Apache License, Version 2.0"
[^z2]: https://raw.githubusercontent.com/ahmetaa/zemberek-nlp/master/README.md "Latest version is 0.17.1 (July 23th 2019)."
[^z3]: https://raw.githubusercontent.com/ahmetaa/zemberek-nlp/master/README.md "This project is now in slow maintenance mode."
[^z4]: https://raw.githubusercontent.com/ahmetaa/zemberek-nlp/master/README.md "Basic spell checker, word suggestion. Noisy text normalization."
[^z5]: https://raw.githubusercontent.com/ahmetaa/zemberek-nlp/master/README.md "gRPC server for access from other languages."
[^z6]: https://raw.githubusercontent.com/ahmetaa/zemberek-nlp/master/README.md "Zemberek-NLP provides Natural Language Processing tools for Turkish."
[^z7]: https://raw.githubusercontent.com/ahmetaa/zemberek-nlp/master/normalization/README.md "It only may correct for 1 insertion, 1 deletion, 1 substitution and 1 transposition errors."
[^zp1]: https://raw.githubusercontent.com/loodos/zemberek-python/master/LICENSE "Licensed under the Apache License, Version 2.0"
[^zp2]: https://raw.githubusercontent.com/loodos/zemberek-python/master/README.md "Normalization (Partially) * Spelling Suggestion"
[^zp3]: https://raw.githubusercontent.com/loodos/zemberek-python/master/README.md "zemberek 0.17.1 and is completely written in Python meaning there is no need to setup"
[^h1]: https://raw.githubusercontent.com/tdd-ai/hunspell-tr/main/LICENSE "Mozilla Public License Version 2.0"
[^h2]: https://raw.githubusercontent.com/tdd-ai/hunspell-tr/main/README.md "| [zemberek-python](https://github.com/Loodos/zemberek-python) | **99.94** | 94.21 | 96.99 | 93.05 |"
[^h3]: https://raw.githubusercontent.com/tdd-ai/hunspell-tr/main/README.md "| [TDD hunspell-tr](https://github.com/tdd-ai/hunspell-tr) (ours) | 99.90 | 97.30 | 98.58 | **94.67** |"
[^h4]: https://raw.githubusercontent.com/tdd-ai/hunspell-tr/main/README.md "Hunspell-tr performs much better in terms error correction accuracy."
[^s1]: https://raw.githubusercontent.com/StarlangSoftware/TurkishSpellChecker-Py/master/LICENSE "GNU GENERAL PUBLIC LICENSE Version 3, 29 June 2007"
[^s2]: https://raw.githubusercontent.com/StarlangSoftware/TurkishSpellChecker-Py/master/README.md "This tool is a spelling checker for Modern Turkish."
[^s3]: https://raw.githubusercontent.com/StarlangSoftware/TurkishSpellChecker-Py/master/README.md "Python 3.13 or higher"
[^s4]: https://raw.githubusercontent.com/StarlangSoftware/TurkishSpellChecker-Py/master/LICENSE "Mere interaction with a user through a computer network, with no transfer of a copy, is not conveying."
[^g1]: https://huggingface.co/GGLab/gec-tr-seq-tagger/raw/main/README.md "Official implementation of sequence-tagger model for Turkish Grammatical Error Correction task."
[^g2]: https://raw.githubusercontent.com/GGLAB-KU/gecturkweb/main/README.md "GECTurk WEB is licensed under the [CC BY-SA 4.0]"
[^g3]: https://raw.githubusercontent.com/GGLAB-KU/gecturk/main/README.md "covering 25 expert-curated grammar rules implemented through transformation functions"
[^g4]: https://raw.githubusercontent.com/GGLAB-KU/gecturk/main/README.md "We present a flexible and extensible synthetic data generation pipeline for Turkish"
[^g5]: https://raw.githubusercontent.com/GGLAB-KU/gecturkweb/main/README.md "Integrates with TrNlp and ZemberekNLP for correcting spelling errors and proper noun capitalization."
[^g6]: https://raw.githubusercontent.com/GGLAB-KU/gecturkweb/main/README.md "Identifies and corrects a variety of Turkish grammatical errors including misuse of diacritics, compound words, foreign words, pronouns, and light verbs."
[^t1]: https://raw.githubusercontent.com/turkic-nlp/turkicnlp/main/README.md "library is Apache-2.0; Apertium GPL-3.0 data downloaded separately"
[^t2]: https://raw.githubusercontent.com/turkic-nlp/turkicnlp/main/README.md "spelling correction; answers that rewrite >30% of a sentence are rejected"
[^t3]: https://raw.githubusercontent.com/turkic-nlp/turkicnlp/main/README.md "**Requirements:** Python 3.10 – 3.12."
[^t4]: https://raw.githubusercontent.com/turkic-nlp/turkicnlp/main/README.md "LLM quality differs strongly between languages (good for Turkish, Kazakh, Uzbek, Azerbaijani; often weak"
[^a1]: https://raw.githubusercontent.com/mozillaz/spellchecker/master/README.md "Project is licensed under MPLv2 License"
[^a2]: https://raw.githubusercontent.com/mozillaz/spellchecker/master/README.md "Hunspell dictionary for Azerbaijani language."
[^a3]: https://raw.githubusercontent.com/az-ai-labs/az-lang-nlp/main/README.md "Uses an embedded frequency dictionary (~86K entries from a 1.25 GB Azerbaijani corpus)"
[^a4]: https://raw.githubusercontent.com/az-ai-labs/az-lang-nlp/main/README.md "Validate Azerbaijani text quality: spelling, punctuation, keyboard layout errors (homoglyphs), and mixed script detection."
[^a5]: https://raw.githubusercontent.com/az-ai-labs/az-lang-nlp/main/README.md "NLP toolkit for Azerbaijani language. Pure Go, zero dependencies."
[^a6]: https://raw.githubusercontent.com/az-ai-labs/az-lang-nlp/main/README.md "Proto definitions and generated client stubs are available in a separate package"
[^j1]: https://raw.githubusercontent.com/tjuzek/ai-34-languages/main/README.md "we compute Log Prevalence Ratio (LPR) metrics to identify words systematically overused by AI relative to human baselines"
[^j2]: https://arxiv.org/abs/2605.25358 "refining a split-halves continuation diagnostic that compares GPT-4.1 continuations with matched human gold-standard text"
[^j3]: https://arxiv.org/abs/2605.25358 "We extend this work to 34 languages in the WMT News Crawl corpus"
[^j4]: https://arxiv.org/html/2605.25358 "Per language, we draw a deterministic random sample of up to 100,000 eligible sentences from the 2020–2021 data."
[^j5]: https://arxiv.org/html/2605.25358 "With 100,000 prompts per language, this gives about 1.2M model tokens and 1.2M human tokens per language for estimating AI overuse."
[^j6]: https://arxiv.org/html/2605.25358 "A minimal system prompt instructs the model to be a useful chat assistant."
[^j7]: https://raw.githubusercontent.com/tjuzek/ai-34-languages/main/README.md "**Model family**: GPT-4.1-mini, Gemini 2.0 Flash, Claude 3 Haiku."
[^j8]: https://arxiv.org/html/2605.25358 "Haiku shares much of the GPT profile, whereas Gemini is more distinct."
[^j9]: https://arxiv.org/html/2605.25358 "Romanian, Russian, Serbian, Spanish, Tamil, Turkish, and Ukrainian"
[^j10]: https://raw.githubusercontent.com/tjuzek/ai-34-languages/main/lexa-index/build_data.py "full = write all rows; compact = drop rows with c_M == 0 to save space."
[^j11]: https://arxiv.org/abs/2605.25358 "Tracking each language's top 20 AI-overused items"
[^j12]: https://arxiv.org/html/2605.25358 "Cross-lingual semantic alignment of AI-overused content words, verified manually on the top-200"
[^j13]: https://raw.githubusercontent.com/tjuzek/ai-34-languages/main/lexa-index/README.md "the CSV outputs (as a 7z, unzip in the top level folder)"
[^j14]: https://raw.githubusercontent.com/tjuzek/ai-34-languages/main/README.md "**Data and word lists:** CC0 1.0 Universal (public domain dedication)"
[^j15]: https://raw.githubusercontent.com/tjuzek/ai-34-languages/main/README.md "**Code:** MIT No Attribution (MIT-0)"
[^j16]: https://arxiv.org/abs/2605.25358 "with 'emphasize'-type verbs appearing in 24 of 34 languages"
[^j17]: https://arxiv.org/html/2605.25358 "Cross-lingual semantic alignment of AI-overused content words, verified manually on the top-200"
[^j18]: https://arxiv.org/html/2605.25358 "The results should therefore be interpreted as characterising the web-news register represented in WMT News Crawl, not news writing in a fully general sense."
[^j19]: https://arxiv.org/html/2605.25358 "Our work is not intended for AI detection, but rather for the identification of broader AI language behaviour."
[^d1]: https://zenodo.org/records/22206304 "The public edition provides texts and writing prompts from 16,519 text families, 18 sources and nine text categories."
[^d2]: https://zenodo.org/records/22206304 "This structure supports comparisons of word choice, sentence patterns and formatting across models and text categories."
[^tr1]: https://dergipark.org.tr/en/download/article-cite-file/1805843/type/6 "The same number of texts on the same topics was also generated by ChatGPT-4o mini, without specifying length."
[^tr2]: https://dergipark.org.tr/en/download/article-cite-file/1805843/type/6 "The lexical diversity ratio was 6.908% in AI texts and 16.304% in student texts."
[^tr3]: https://dergipark.org.tr/en/download/article-cite-file/1805843/type/6 "The total number of idioms was 1,038 in AI texts and 559 in student texts, with 107 and 205 type idioms respectively."

## Open questions

- **Hosted Turkish grammar API.** No hosted API for Turkish grammar or spelling turned up beyond the
  GECTurk web demo (gecturk.net), which has no documented API (Unverified). LanguageTool's lack of
  Turkish is taken from the caller's brief and was not re-checked here.
- **List sizes.** How many rows per language the ai-34-languages CSVs hold, and how many pass the
  count guard, is unknown: the 7z archive was not unpacked (this agent cannot run a shell).
- **Real accuracy.** None of the Turkish checkers has been tried on text written by models. All
  accuracy figures above come from human misspellings (trspell-10) or synthetic errors (GECTurk),
  not from motivation letters.
- **Hunspell from Python.** Which Hunspell binding (C-library `hunspell`, or a pure-Python port)
  works on the production image was not checked.
