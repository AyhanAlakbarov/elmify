# The sweep writer in 42 languages — screened 2026-10-13

**2026-10-14: the sentences no longer name the master's level** (owner decision, recorded in
`2026-10-13-sweep-sentence-writing-comparison.md`), so the level-word findings below — the Italian,
French, Danish and Slovenian corrections, Irish, Icelandic and Swiss German — are history; the
screen has no level column.

`manage.py check_angle_writer` asks `SWEEP_ANGLE_MODEL` (DeepSeek V4.1 Flash) for one foundation
angle set in every language the 53 target countries' sweeps run in (42 languages, from
`languages.CldrLanguages`), stores nothing, and counts by code: sentences returned (18 asked
for), the share carrying a kind word and the level word, whether this year's call names the
cycle in digits, and what the generator would drop. About $0.10 for all three runs below.
Sentences: `~/agent-workspace/elmify-runs/angle-writer-check-2026-10-13/`.

## What the first run found, and what was done

| Found | Done |
|---|---|
| 12 of 42 languages came back short: German and Georgian wrote only the application page, three times; Slovenian, Chinese and Armenian one sentence per page type; Maltese one meaningless sentence ("samples ignored by schema? no") | `angles.ask_angle_set` asks **once more** when the answer is short or off-schema, and merges the two without repeating a sentence. Never a loop. |
| Wikidata's Italian word for master's degree is the English phrase "master's degree" | correction: `laurea magistrale` (mur.gov.it) |
| Its French word is "maîtrise", the Quebec term — sentences said "bourses de maîtrise" for Belgium | correction: `master` (monmaster.gouv.fr) |
| Its Danish word is the obsolete "magister" — sentences said "magisterstuderende" | correction: `kandidat` (ug.dk) |
| The checker scored Japanese, Chinese (no spaces) and Irish (initial mutation, "bhfondúireacht") as 0% | the checker matches a word's stem inside a token, not only at its start |

A filter dropping every sentence without a kind word was tried and **removed**: sensible sentences
leave the kind word out ("Burs başvurusu nasıl yapılır?"), and Greek, Finnish, Russian and Armenian
used one in only 75–94% of sentences, so it would have cut breadth to catch one bad sentence.

## After the fixes

33 of 42 languages returned the full 18 sentences; German, Croatian, Maltese, Polish, Portuguese and
Chinese returned 12, Georgian 3. Kind words appeared in 83–100% of sentences in every language but
three (below), the level word in 92–100% in all but Irish. Years were in digits everywhere.

## Second round, 2026-10-14: every language returns 18

| Found | Done |
|---|---|
| Georgian's answer was cut off: about one token per character, so 18 sentences and their keyword versions filled the 3,000-token output cap and came back off-schema | `_MAX_OUTPUT_TOKENS` 10,000. DeepSeek bills tokens as written, so a short answer costs the same |
| The short languages wrote one angle and stopped: DeepSeek read `samples: 3` as three sentences in all | the request now says "3 for each of the 6 angles, 18 queries in all", and the instruction says every angle |
| Slovenian showed 0% level word while every sentence said "magistrski študij": Wikidata's "magisterij" is the pre-Bologna degree, as Danish "magister" was | correction: `magistrski študij` (uni-lj.si) |

Full rerun of all 42 languages: **42 of 42 return 18 sentences**, Georgian 3 per angle (one retry).
Still flagged by the screen: Irish level word 78%; Nynorsk and Russian kind words 78%; Icelandic and
Swiss German have no level word. Sentences: `sentences_final.json`, counts `report_final.txt`.

## Still open

- **Irish**: the level word ("céim máistreachta") moves between runs (11%, 78%, 100%). Irish
  universities and funders publish in English, which runs too.
- **Nynorsk** and **Russian** use other words for the funder in about a fifth of sentences
  (Swedish and Latvian did on the first run and were above 80% on this one); a reader of each
  should look before a sweep there.
- **Icelandic** and **Swiss German** have no level word on Wikidata; their sentences name no level.
- One run per language: the counts move between runs. The screen finds languages to look at; it
  does not grade them.
