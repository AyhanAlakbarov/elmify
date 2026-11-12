# Research wiki — design

Approved by the owner 2026-10-26 ("Approved: the research wiki as proposed"). Plan:
`docs/superpowers/plans/2026-10-26-research-wiki.md`.

## 1. Why

Sessions keep re-reading the funding and discovery research in `docs/superpowers/research/` to answer
the same questions: its prose was opened 135 times in 15 sessions (transcript count, 2026-10-25, by
file path; answers given without opening a file are not counted). The same countries and schemes
recur across 13 separate syntheses, so a question about one country means reading several of them.

A wiki — the pattern in Karpathy's "LLM Wiki" note (gist 442a6bf5) — is a set of short Markdown
pages a model maintains between the raw sources and the questions: one page per topic, country and
scheme, each claim cited to its source. A session reads `index.md`, then a few pages, instead of the
syntheses.

## 2. What it is

```
docs/superpowers/research/      the raw sources: never edited by the wiki
docs/wiki/
  index.md                      every page: link, one-line summary, under its kind's heading
  log.md                        append-only: ## [YYYY-MM-DD] ingest | <file>, or skip | <file> | <reason>
  open-questions.md             disagreements between sources, unverified claims, gaps
  topics/<slug>.md              one per synthesis; slug = the synthesis filename without date and "-synthesis"
  countries/<iso2>.md           az, tr, de, kr, ...
  schemes/<slug>.md             fulbright, gks, erasmus-mundus, daad, ...
  sources/<slug>.md             registers, search providers, open-data sources and their terms
.claude/rules/research-wiki.md  the conventions; loads when a file under docs/wiki/ or the research folder is read
scripts/wiki_lint.py            the parser the test uses, and the on-demand report
tests/test_research_wiki.py     the checks that run with the suite
```

**Page rules**
- A claim ends with its source: `[src: <research filename> §<n>]`, where `<n>` is a numbered heading
  (`## 3. ...`) in that file; `§<n>` is left out when the file has no numbered headings.
- Where two sources disagree, the page gives both, each cited, and `open-questions.md` gets a line.
- A country or scheme gets a page only when at least two sources say something about it; otherwise
  the fact stays on its topic page.
- Data stays in its CSV files; a page links to the file instead of copying rows.
- A page stays under about 60 lines. The syntheses remain the long-form record.

## 3. How sessions use it

`CLAUDE.md` gets one always-loaded line: a question about funding, schemes, countries, institutions
or discovery sources starts at `docs/wiki/index.md`. The rules file says the rest: answer from the
pages with their citations, open a raw source only for what the pages lack, and offer to ingest it
when the pages lacked it.

## 4. How it stays current

1. **Ingest with the research.** A pull request that adds a research file under
   `docs/superpowers/research/` also updates the pages it touches, `index.md` and `log.md` (or logs a
   `skip` with a reason). The rules file says so.
2. **The suite checks the wiki** (`tests/test_research_wiki.py`, no model calls): every cited file
   and section exists, every relative link resolves, index and pages list each other, every content
   page cites at least one source, every file `log.md` names exists. A renamed or deleted research
   file fails the suite until the wiki is fixed.
3. **An on-demand report** (`python scripts/wiki_lint.py`, no model calls, always exits 0): research
   files with no `ingest` or `skip` line, pages no other page links to, and pages last committed
   before a source they cite was last committed (stale). It reports; it never blocks new research.
4. **Contradiction review** works through `open-questions.md` when the owner asks: the only part
   that calls a model.

## 5. First build and measurement

- **Ingest** the 13 syntheses, the 4 verification notes (`fulbright-per-country`,
  `gapfill-openitem`, `gks-quota-primary`, `government-inbound`),
  `register-open-questions-closed` and `three-remaining-gaps`: 19 files, about 39k words (~52k
  tokens). The 26 reviews come in only where a synthesis cites one for a fact. Every other research
  file is logged as `skip` with its reason (CV, transcript and portal research has its own home in
  `.claude/rules/cv-and-letters.md`). Expected size: about 50 pages. Expected cost: $5–15 one-off;
  an estimate, not measured.
- **Measure** with three fixed questions, each run headless once before the wiki exists (on master)
  and once after (on the branch), same prompt and model, spend from
  `~/agent-workspace/evals/usage/session_spend.py`, citations checked by hand against an answer key
  written from the raw files before the first run.
- **Keep or drop:** keep the wiki if the three runs together use at least 30% fewer input tokens and
  no answer loses a correct fact or citation the baseline had; otherwise one pull request deletes
  `docs/wiki/`, the rules file, the script and the test. One run per question is noisy; the owner
  decides on the numbers.

## 6. Not doing

No embeddings or vector search (an index file serves a few hundred pages). No edits to the raw
research. No scheduled runs. No wiki for `docs/research/` (CV and letter research) until this one
has proved itself. Nothing outside tehsil.
