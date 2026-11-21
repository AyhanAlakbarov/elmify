---
paths:
  - "docs/wiki/**"
  - "docs/superpowers/research/**"
---

## Research wiki: answer funding and discovery questions from docs/wiki/

<!-- Owner-approved 2026-10-26. Design: docs/superpowers/specs/2026-10-26-research-wiki-design.md -->

`docs/wiki/` holds short, cited pages built from `docs/superpowers/research/`: one per synthesis
topic, country, scheme and source. Start a funding or discovery question at `docs/wiki/index.md`,
answer from the pages with their citations, and open a raw research file only for what the pages
lack; then offer to add it to the wiki.

Writing or changing a page:
- Every claim ends with `[src: <research filename> §<n>]`, `<n>` a numbered heading in that file
  (leave `§<n>` out when it has none). Never edit the research files themselves.
- Two sources disagree: give both, each cited, and add a line to `docs/wiki/open-questions.md`.
- A research conclusion a later spec or doc replaced: keep it, cited, and add `Superseded: <what changed> — see [<doc>](<relative link>)`.
- A country (`countries/<iso2>.md`) or scheme (`schemes/<slug>.md`) gets a page only when two
  sources say something about it; otherwise the fact stays on its topic page.
- Keep a page under about 60 lines; link CSV data instead of copying it.
- List every page in `index.md` under its kind, with a one-line summary.

Adding research: the pull request that adds a file under `docs/superpowers/research/` also updates
the pages it touches, `index.md`, and appends `## [YYYY-MM-DD] ingest | <filename>` to `log.md`, or
`## [YYYY-MM-DD] skip | <filename> | <reason>` when it holds nothing a page needs.

Checks: `tests/test_research_wiki.py` runs with the suite (missing sources or sections, dead links,
index out of step, uncited pages). `python scripts/wiki_lint.py` also reports research not yet
ingested, pages nothing links to, and pages older than a source they cite.
