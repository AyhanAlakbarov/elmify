# Letter languages and the tooling that covers each (2026-10-14)

Scope: which languages a Elmify motivation letter may have to be written in, and, for each one, what
exists to check it beyond the writer model. The engine's quality checks were built for English,
German, French, Russian, Turkish and Azerbaijani. The table below shows where a default is needed.

## Answers first

- **Languages the repo already says a letter may need (15):** English, German, French, Italian,
  Spanish, Portuguese, Russian, Turkish, Azerbaijani, Arabic, Chinese, Japanese, Korean and Afrikaans
  are named in the "Language required" column of `docs/research/letter-shape-country-map.csv`.
  Dutch comes from the same file's Netherlands row, "Programme language (Utrecht rule)". Swiss
  rows say "Language of instruction", which adds nothing new (German, French, Italian).
  - Sweden's row says "English", so Swedish counts as possible, not observed.
- **Languages the owner's destination list makes possible but no repo row names (25, Swedish included):** the
  other official languages of the EU, Norway, Iceland, Serbia, Vietnam, Armenia, Georgia, Kazakhstan
  and Brunei. These are inferred from the destination list (see Sub-question 1), not observed
  requirements.
- **Biggest gaps:**
  - **Malay** and **Georgian**: almost nothing exists beyond the writer model. Georgian has only a
    Hunspell dictionary. Malay has only spaCy's tokenizer-level language data.
  - **Maltese** has only a Stanza pipeline.
  - **Azerbaijani**, **Armenian** and **Vietnamese** have spelling dictionaries and Stanza (not
    Azerbaijani), but no LanguageTool and no ai-34 list.
- **Sentence splitting is broken today for four scripts, whatever the language tooling:**
  `apps/documents/letter_gates.py:44` splits on `(?<=[.!?])\s+`.
  - Chinese and Japanese end sentences with 。 and put no space after it, so the regex never splits
    them.
  - The Armenian full stop ։ and the Arabic question mark ؟ are Unicode sentence terminators the
    regex does not know.
  - Greek writes its question mark as `;`.
  - `script_of` (`letter_gates.py:301-317`) knows only Hangul, Kana and Han. Every Cyrillic, Greek,
    Arabic, Armenian or Georgian letter is treated as Latin script.

## Sub-questions

1. Which languages may a letter need, from the repo (country map, owner destination list, PR #147)?
2. Per language: (a) LanguageTool support, (b) tjuzek/ai-34-languages coverage, (c) a spaCy or Stanza
   pipeline, (d) a Hunspell dictionary, (e) script and sentence-boundary handling.
3. Which languages have nothing beyond the writer model?

The four tools in question 2 were named by the caller, so no discovery search was run to build an
option list. **Missing or unused in this session:** Exa, Brave and Tavily were not needed (every
fact came from a named primary page). Context7 was not used, because the spaCy and Stanza language
tables are on their own sites. `git.libreoffice.org` and `packages.debian.org` refused automated
reads (Anubis and a bot challenge). The GitHub mirror of LibreOffice's dictionaries and Debian's
`qa.debian.org/madison.php` were read instead.

## 1. What the repo says

- **Owner destination list.** Recorded in memory file
  `~/.claude-elmify/projects/-home-orkhan-Desktop-elmify/memory/destination-country-coverage.md`
  (owner, 2026-09-26): all EU, NO, CH, IS, UK, SA, AE, QA, KW, BH, AU, NZ, SG, BN, RS, TR, CN, JP,
  KR, RU, VN (top universities only), AM/AZ/GE, KZ, US, CA, plus top universities only in Africa,
  South America and Mexico. Students at launch are from Azerbaijan.
  - **No file under `apps/` or `docs/` holds this list.** PR #147 ("Cover every destination
    country in the catalogue list", merged 2026-09-26) cites "the owner's 2026-09-26 list" in its
    body but stores domains, not countries (read via the GitHub API, PR body).
- **Country to letter language.** `docs/research/letter-shape-country-map.csv` has a
  "Language required" column, one row per institution or scheme. Its values include:
  - "Programme language (TUM Informatics: English)"
  - "French or programme language"
  - "Russian or English"
  - "Azerbaijani, Turkish, English or Russian" (Heydar Aliyev grant)
  - "Japanese or English" (MEXT)
  - "English or Korean" (GKS)
  - "Chinese or English" (CSC)
  - "English or Arabic per programme" (Bahrain)
  - "English (Afrikaans accepted at Stellenbosch)"
  - Spanish (UNAM, Chile, Peru) and Portuguese (Brazil)
  - "English or Italian" (Polimi)

  Georgia, Armenia, Kenya, Nigeria, Rwanda and Central Asia are "unassigned" or "no source found".
- **Site-language table.** `apps/documents/research_fit/anchors.py:51-55` (`_SITE_LANGUAGE`) maps 22
  countries to a site language: de, tr, nl, fr, it, es, pt, sv, no, da, fi, hu, pl, cs, az, ru,
  ja, ko. It is for search queries, not letters, but it confirms which non-English sites the
  engine already expects.
- **Lettering system by country.** `apps/documents/letter_defaults.py:53-64`
  (`COUNTRY_SYSTEM`) covers 33 countries. Any other country falls back to System B. This is the
  letter's shape, not its language.

**Which languages count as "needed":** a letter is written in English or in the programme's
language of instruction, or in a language the scheme prescribes (the brief's rule). So:

- **Observed:** the 15 languages in "Answers first".
- **Possible:** the official language of each destination where a master's might be taught in it.
  These are Swedish, Danish, Norwegian, Finnish, Icelandic, Polish, Czech, Slovak, Slovenian, Croatian,
  Hungarian, Romanian, Bulgarian, Greek, Estonian, Latvian, Lithuanian, Maltese, Serbian,
  Vietnamese, Armenian, Georgian, Kazakh, Malay and Catalan.
  - That none of these is ever actually required is **Unverified**. The map's Nordic, Czech,
    Estonian and Georgian rows all say English.
  - Thai, Hebrew and Persian are not on the destination list.

## 2. Coverage table

What each column means and where it comes from:

- **LT**: LanguageTool 6.6 rule counts (XML rules), or "–" when the language is not on the
  page.[^lt1] "spell" means LanguageTool also spell-checks it. Chinese and Japanese have rules but
  no spell check.[^lt3][^lt4]
- **ai-34**: listed in the paper's 34 languages.[^j0]
- **spaCy**: "trained" means trained pipelines exist. "data only" means the "none yet" row, where
  spaCy has language data but no pipeline.[^sp0]
- **Stanza**: has a UD pipeline on the performance page.[^st0]
- **Hunspell**: a dictionary in wooorm/dictionaries (which "crawls dictionaries from several
  sources")[^w0], LibreOffice's dictionary repository[^lo0] or Debian.
- **Script / boundaries**: Unicode sentence-break facts.

| Language | Need | LT | ai-34 | spaCy | Stanza | Hunspell | Script / boundaries |
|---|---|---|---|---|---|---|---|
| English | always | 6074, spell[^lt2] | yes | trained | yes | yes | Latin; ICU has abbreviation filters[^icu2] |
| German | observed | 5224, spell | yes | trained | yes | yes | Latin; ICU abbreviations |
| French | observed | 6984, spell | yes | trained | yes | yes (MPL-2.0) | Latin; ICU abbreviations |
| Spanish | observed | 1644, spell | yes | trained | yes | yes | Latin; ICU abbreviations |
| Portuguese | observed | 2919, spell | yes | trained | yes | yes | Latin; ICU abbreviations |
| Italian | observed | 141, spell[^lt5] | yes | trained | yes | yes | Latin; ICU abbreviations |
| Dutch | observed | 3500, spell | yes | trained | yes | yes | Latin |
| Swedish | possible (Uppsala/KTH rows say English) | 32, spell[^lt6] | **no** | trained | yes | yes | Latin |
| Russian | observed | 892, spell | yes | trained | yes | yes (BSD-3) | Cyrillic; `script_of` treats it as Latin |
| Turkish | observed | – | yes | data only[^sp1] | yes[^st1] | yes (MIT)[^w1] | Latin |
| Azerbaijani | observed | – | **no** | data only[^sp2] | **no** | yes (Mozilla, MPL-2.0)[^az1] | Latin |
| Arabic | observed | 450, spell[^lt7] | yes | data only[^sp3] | yes[^st2] | yes[^deb1] | Arabic, right to left; ؟ is a sentence terminator[^u2] |
| Chinese | observed | 1863, no spell[^lt3] | yes | trained | yes | n/a | Han; 。 is a terminator[^u3] with no space after it; ICU segments words with a dictionary[^icu1] |
| Japanese | observed | 735, no spell[^lt4] | yes | trained | yes | n/a | Kana and Han; same as Chinese |
| Korean | observed | – | yes | trained[^sp4] | yes | yes[^w2] | Hangul with spaces |
| Afrikaans | observed (Stellenbosch) | – | yes[^j1] | data only | yes | yes[^deb2] | Latin |
| Catalan | possible (Unverified) | 8251, spell[^lt8] | no | trained | yes | yes | Latin |
| Danish | possible | 78, spell | no | trained | yes | yes | Latin |
| Norwegian | possible | spell only[^lt2b] | no | trained (nb)[^sp5]; data only (nn) | yes (nb, nn) | yes (nb, nn) | Latin |
| Finnish | possible | – | yes | trained | yes | not Hunspell; Voikko instead[^deb3] | Latin |
| Icelandic | possible | – | yes | data only | yes | yes (CC-BY-SA-3.0) | Latin |
| Polish | possible | 1747, spell | yes | trained | yes | yes | Latin |
| Czech | possible | – | yes | data only | yes | yes (GPL-2.0) | Latin |
| Slovak | possible | 170, spell | no | data only | yes | yes | Latin |
| Slovenian | possible | 86, spell | no | trained | yes | yes | Latin |
| Croatian | possible | – | yes | trained | yes | yes | Latin |
| Serbian | possible | – | yes | data only | yes | yes (Cyrillic and Latin) | Cyrillic or Latin |
| Hungarian | possible | – | no | data only | yes | yes | Latin |
| Romanian | possible | 457, spell | yes | trained | yes | yes | Latin |
| Bulgarian | possible | – | yes | data only | yes | yes | Cyrillic |
| Greek | possible | 55, spell[^lt9] | yes | trained | yes | yes | Greek; the Greek question mark is `;`, and U+037E is **not** a sentence terminator in Unicode[^u4] |
| Estonian | possible | – | yes | data only | yes | yes | Latin |
| Latvian | possible | – | yes | data only | yes | yes | Latin |
| Lithuanian | possible | – | yes | trained | yes | yes | Latin |
| Maltese | possible | – | no | not listed | yes[^st3] | none found | Latin |
| Vietnamese | possible | – | no | data only[^sp6] | yes, tokens 88.02[^st4] | yes (GPL-2.0) | Latin with diacritics |
| Armenian | possible | – | no | data only[^sp7] | yes[^st5] | yes[^w3] | Armenian; full stop ։ is a terminator[^u1] |
| Georgian | possible | – | no | not listed | not listed | yes (MIT)[^w4] | Georgian |
| Kazakh | possible | – | yes[^j2] | not listed | yes, LAS 51.38[^st6] | yes[^deb4] | Cyrillic |
| Malay | possible (Brunei; map says English) | – | no (Indonesian only) | data only[^sp8] | no (Indonesian only) | none found | Latin |

Notes on reading the table:

- **"–" in the LT column** means the language is not in the 6.6 table. Turkish, Korean, Czech,
  Croatian, Serbian, Hungarian, Finnish, Bulgarian, the Baltic languages, Icelandic, Maltese,
  Vietnamese, Armenian, Georgian, Kazakh, Malay, Azerbaijani and Afrikaans are all absent from
  it.[^lt1] The page is dated 2025-03-27, so a later LanguageTool release may add some
  (**Unverified**).
- **ai-34 languages** are af, ar, bg, cs, de, el, en, es, et, fa, fi, fr, hi, hr, id, is, it, ja,
  kk, ko, ky, lt, lv, mr, nl, pl, pt, ro, ru, sr, ta, tr, uk, zh. Swedish, Danish, Norwegian,
  Hungarian, Slovak, Slovenian, Catalan, Maltese, Vietnamese, Armenian, Georgian, Azerbaijani and
  Malay are not among them.[^j0]
- **Hunspell "none found"** means absent from all three: wooorm's 92-dictionary list[^w0], the
  LibreOffice repository's directories[^lo0] and Debian trixie (`hunspell-ms` and `hunspell-mt`
  returned no rows on `qa.debian.org/madison.php`). A dictionary elsewhere is not ruled out.
- **Two Hunspell caveats.**
  - A LibreOffice directory can hold hyphenation or thesaurus files only; that each listed
    directory holds a spelling dictionary is **Unverified**.
  - Hunspell licences vary by language: GPL-only for Czech, Italian, Vietnamese and Norwegian;
    MIT for Turkish and Georgian.[^w0]
- **Sentence boundaries.**
  - **ICU** follows UAX #29 for sentences. It has dictionary-based word segmentation for Chinese,
    Japanese, Thai, Lao, Khmer and Burmese.[^icu1] Its abbreviation filters exist only for six
    languages.[^icu2]
  - **spaCy** ships a multi-language ("xx") entry with 2 packages.[^sp9] That one of them is a
    sentence splitter is **Unverified** here.

## 3. Languages with nothing beyond the writer model

- **None is completely bare.** Every language in the table has at least one of: a spelling
  dictionary, a Stanza pipeline, spaCy language data, or Unicode sentence rules.
- **Practically bare** (at most one non-model tool):
  - **Malay**: only spaCy's tokenizer-level language data. No grammar, no AI-word list, no
    Hunspell found, no Stanza.
  - **Georgian**: only a Hunspell dictionary. No LanguageTool, ai-34, spaCy or Stanza.
  - **Maltese**: only Stanza (lemmas and sentence splitting). No grammar, no word list, no
    Hunspell found.
- **Spelling only:** Azerbaijani (Hunspell, plus the Go library in the 2026-10-14 Turkish note). It
  has no Stanza pipeline and no AI-word list.
- **Low need for these four:** in the country map, every row for Brunei, Malaysia, Georgia and the
  Azerbaijani grant accepts English (Azerbaijani is optional for the grant). So these languages
  matter only if a programme taught in them is ever added.

**Suggested default for an uncovered language (for the spec to accept or reject).**

- **Sentence splitting:** Unicode UAX #29 sentence segmentation (ICU) in place of the
  `[.!?]\s+` regex, plus Greek `;` as an extra terminator.
- **Spelling:** Hunspell where a dictionary exists.
- **Grammar and stock words:** the writer model's own judgement, with the language flagged as
  "unchecked".

That ICU is available in the production image is **Unverified**.

## Sources

[^lt1]: https://dev.languagetool.org/languages "Rules in LanguageTool 6.6 Date: 2025-03-27"
[^lt2]: https://dev.languagetool.org/languages "English Variants for: Australian, Canadian, GB, New Zealand, South African, US 6074"
[^lt2b]: https://dev.languagetool.org/languages "spell checking only (no grammar checks): Norwegian"
[^lt3]: https://dev.languagetool.org/languages "Chinese 1863 Browse , XML 1 0"
[^lt4]: https://dev.languagetool.org/languages "Japanese 735 Browse , XML 0 0"
[^lt5]: https://dev.languagetool.org/languages "Italian 141 Browse , XML 3 ✓ 0"
[^lt6]: https://dev.languagetool.org/languages "Swedish 32 Browse , XML 2 ✓ 0"
[^lt7]: https://dev.languagetool.org/languages "Arabic 450 Browse , XML 16 ✓ 0"
[^lt8]: https://dev.languagetool.org/languages "Catalan Variants for: Balearic, Valencian 8251"
[^lt9]: https://dev.languagetool.org/languages "Greek 55 Browse , XML 5 ✓ 0"
[^j0]: https://raw.githubusercontent.com/tjuzek/ai-34-languages/main/README.md "34 languages are included in the study:"
[^j1]: https://raw.githubusercontent.com/tjuzek/ai-34-languages/main/README.md "| af | Afrikaans | fa | Persian | ko | Korean | pt | Portuguese |"
[^j2]: https://raw.githubusercontent.com/tjuzek/ai-34-languages/main/README.md "| et | Estonian | ja | Japanese | kk | Kazakh |"
[^sp0]: https://spacy.io/usage/models "Language Code Language Data Pipelines"
[^sp1]: https://spacy.io/usage/models "Turkish tr lang/tr none yet"
[^sp2]: https://spacy.io/usage/models "Azerbaijani az lang/az none yet"
[^sp3]: https://spacy.io/usage/models "Arabic ar lang/ar none yet"
[^sp4]: https://spacy.io/usage/models "Korean ko lang/ko 3 packages"
[^sp5]: https://spacy.io/usage/models "Norwegian Bokmål nb lang/nb 3 packages"
[^sp6]: https://spacy.io/usage/models "Vietnamese vi lang/vi none yet"
[^sp7]: https://spacy.io/usage/models "Armenian hy lang/hy none yet"
[^sp8]: https://spacy.io/usage/models "Malay ms lang/ms none yet"
[^sp9]: https://spacy.io/usage/models "Multi-language xx lang/xx 2 packages"
[^st0]: https://stanfordnlp.github.io/stanza/performance.html "Language Treebank lcode Default Tokens Sentences Words"
[^st1]: https://stanfordnlp.github.io/stanza/performance.html "Turkish IMST tr 99.86"
[^st2]: https://stanfordnlp.github.io/stanza/performance.html "Arabic PADT ar 99.98"
[^st3]: https://stanfordnlp.github.io/stanza/performance.html "Maltese MUDT mt 99.85"
[^st4]: https://stanfordnlp.github.io/stanza/performance.html "Vietnamese VTB vi 88.02"
[^st5]: https://stanfordnlp.github.io/stanza/performance.html "Armenian BSUT hy 99.91"
[^st6]: https://stanfordnlp.github.io/stanza/performance.html "Kazakh KTB kk 99.42 100.00 96.85 85.58 86.15 78.70 74.50 89.21 60.55 51.38"
[^w0]: https://raw.githubusercontent.com/wooorm/dictionaries/main/readme.md "In total 92 dictionaries are provided."
[^w1]: https://raw.githubusercontent.com/wooorm/dictionaries/main/readme.md "[`dictionary-tr`](dictionaries/tr) | Turkish | [MIT](dictionaries/tr/license) |"
[^w2]: https://raw.githubusercontent.com/wooorm/dictionaries/main/readme.md "[`dictionary-ko`](dictionaries/ko) | Korean |"
[^w3]: https://raw.githubusercontent.com/wooorm/dictionaries/main/readme.md "[`dictionary-hy`](dictionaries/hy) | Armenian |"
[^w4]: https://raw.githubusercontent.com/wooorm/dictionaries/main/readme.md "[`dictionary-ka`](dictionaries/ka) | Georgian | [MIT](dictionaries/ka/license) |"
[^lo0]: https://github.com/LibreOffice/dictionaries "af_ZA af_ZA an_ES an_ES ar ar"
[^az1]: https://raw.githubusercontent.com/mozillaz/spellchecker/master/README.md "Hunspell dictionary for Azerbaijani language."
[^deb1]: https://qa.debian.org/madison.php?package=hunspell-ar&text=on&s=trixie "hunspell-ar | 3.5.2014-11-08-5 | trixie | source, all"
[^deb2]: https://qa.debian.org/madison.php?package=hunspell-af&text=on&s=trixie "hunspell-af | 1:25.2.3-1 | trixie | all"
[^deb3]: https://qa.debian.org/madison.php?package=voikko-fi&text=on&s=trixie "voikko-fi | 2.5-2 | trixie | source"
[^deb4]: https://qa.debian.org/madison.php?package=hunspell-kk&text=on&s=trixie "hunspell-kk | 1.1.2-2 | trixie | source, all"
[^u1]: https://util.unicode.org/UnicodeJsps/character.jsp?a=0589 "Sentence_Break STerm Sentence_Terminal Yes"
[^u2]: https://util.unicode.org/UnicodeJsps/character.jsp?a=061F "Sentence_Break STerm Sentence_Terminal Yes"
[^u3]: https://util.unicode.org/UnicodeJsps/character.jsp?a=3002 "Sentence_Break STerm Sentence_Terminal Yes"
[^u4]: https://util.unicode.org/UnicodeJsps/character.jsp?a=037E "Sentence_Break SContinue Sentence_Terminal No"
[^icu1]: https://unicode-org.github.io/icu/userguide/boundaryanalysis/ "ICU provides dictionary support for word boundaries in Chinese, Japanese, Thai, Lao, Khmer and Burmese."
[^icu2]: https://unicode-org.github.io/icu/userguide/boundaryanalysis/ "Abbreviation lists are available (as of ICU 64) for English, German, Spanish, French, Italian and Portuguese."

## Open questions

- **Is any "possible" language ever actually required?** No repo row shows a programme demanding
  a letter in Danish, Czech, Vietnamese, Georgian and so on. The map's rows for those countries
  say English. One per-country pass would settle it.
- **Newer LanguageTool releases.** The languages page is for 6.6 (2025-03-27). Whether a later
  release added Turkish, Korean or another missing language was not checked.
- **Hunspell contents.** Whether each LibreOffice directory holds a spelling dictionary rather than
  hyphenation only was not checked. Malay and Maltese dictionaries outside the three lists were
  not searched for.
- **Stanza Georgian and Azerbaijani.** Both are absent from the performance page. A model trained
  outside UD, or a newer Stanza release, was not checked.
- **spaCy "xx" packages.** Which two packages the multi-language entry holds, and whether one is a
  sentence splitter usable for uncovered languages, was not read.
- **ICU in production.** Whether PyICU (or another UAX #29 implementation) is installable on the
  production image was not checked.
