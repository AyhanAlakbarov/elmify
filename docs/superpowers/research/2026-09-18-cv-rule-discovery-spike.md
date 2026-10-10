# Can discovery reach the pages that state CV rules? Measured before building it

**Question.** The corpus baseline is 0.00 on every metric (`2026-09-16-cv-corpus-baseline.md`),
measured on a pipeline that reads only each programme's seed page. Before building the discovery
subsystem specified in `specs/2026-09-17-cv-rule-discovery-design.md`, is the thing it depends on
even possible: can enumeration put the page that states a CV rule in front of the model, and does
the rule's own sentence survive the fetch?

**Method.** Two passes, no model calls in either, so nothing here measures derivation.

1. **Reach.** For each of the 18 dev programmes carrying an accepted corpus rule, enumerate from its
   `seed_url` with Firecrawl `/map` (`limit: 300`, `includeSubdomains: true`) unioned with Tavily
   `/map` (`max_depth: 2`, `limit: 100`, **`allow_external: false`**), rank the union by a
   deliberately naive heuristic — count of admissions-ish words **in the URL path only** — and ask
   whether each of the 24 labelled rule URLs is in the enumeration, and at what rank.
2. **Survival.** Fetch each reached page and ask whether the corpus's labelled sentence for each of
   the 28 accepted rules on those pages is present in the fetched text.

Throwaway probe; the script is in the session scratchpad and nothing was persisted into the product.
Cost: ~18 Firecrawl map calls, ~18 Tavily map calls, 40 Firecrawl scrapes.

## 1. Reach — 20 of 24 URLs, 16 of 18 programmes

| | count |
|---|---|
| labelled URLs reachable by enumeration | **20 / 24** |
| …at rank ≤ 5 under the naive ranker | 15 / 20 |
| …at rank ≤ 10 | 17 / 20 |
| programmes reaching at least one labelled page | **16 / 18** |
| Firecrawl `/map` alone | 17 / 24 |
| Tavily `/map` alone | 13 / 24 |

**The union is worth having, again.** 17 and 13 separately, 20 together — each found targets the
other missed (`mathmods/apply/requirements` and `sbfi` FAQ came from Tavily only; `fulbright-nepal`
and `europubhealth` from Firecrawl only). This is the third independent measurement agreeing the two
maps are complementary rather than redundant.

**The naive ranker did better than the design feared.** Counting admissions words in the URL path,
with no page content and no model, put three quarters of the found targets in the top five. The
`careers_decoy` problem the spec treats as the central difficulty does not appear in this
population — see the limits below for why that is not reassurance.

**Both misses are informative, and neither is a ranking failure.**

- `daad-epos`'s labelled page is `www2.daad.de/…/21148-scholarship-database?…&detail=50076777` — a
  **database query result**, not a page in the site's structure. No enumeration of a host reaches it,
  because it is not part of the host's link graph. A programme whose rules live behind a search form
  needs a different instrument, not a better crawler.
- `i-mesc.eu/application/student` was missed by both maps. The 2026-09-15 note records the same
  site's `/map` behaving oddly (the `search` filter returning zero where unfiltered returned 76).

Two further "misses" are not misses of the rule: `emjm-imaging`'s Q&A page was absent but its parent
`/application-and-admission` came back at **rank 1**, and `fau-ai-msc`'s
`/prospective-students/application-master` was absent but the sibling path carrying the identical
sentence came back at rank 9.

## 2. Survival — 28 of 28

Every accepted rule's labelled sentence is present in the fetched page. **The evidence is not lost
between finding the page and handing it to the model.**

**A false result on the way there is worth recording, because it is a trap.** A first pass scored
16/28, and the twelve "missing" sentences were all present — they differed only in markdown. The
corpus's sentences were pooled through Tavily (`* **CV/Résumé**`, `2. CV (use the Europass template
available here: );` with the link stripped) and were being compared against Firecrawl's rendering of
the same pages. **Comparing two extractors' markdown measures the extractors, not the page.** Strip
link syntax and non-alphanumerics and compare the content words: 28/28. Any future check of this
kind must normalise before it compares, or it will report a content problem that does not exist.

*Why the extractor changed mid-probe:* Tavily returned **HTTP 432, "This request exceeds your plan's
set usage limit"** — the month's credits were spent. Firecrawl `/scrape` substituted, which the
2026-09-15 comparison had already measured as equivalent on real programme pages.

## 3. What this does and does not license

**Answers:** discovery is possible. The pages are reachable from the seed by ordinary enumeration,
cheap ranking finds them, and the evidence survives the fetch. The 0.00 baseline is a consequence of
reading only the seed page, not of the rules being unreachable.

**Does not answer: derivation.** Turning a found sentence into the right rule is untouched here, and
it is the part already measured as unstable — three readings of one page returning 29-40 statements,
and the format judge needing unanimity across two model families to be safe
(CLAUDE.md, "LLM/AI security").

**The population is the easy half, and this is the limit that matters.** These 18 programmes are the
ones carrying accepted corpus rules, which are overwhelmingly Erasmus Mundus consortia and funder
schemes — the class already measured as rule-rich (10 of 11 consortia publish a rule; 2 of 6
universities do). The known-hard cases are **absent by construction**: a programme with no accepted
rule cannot be scored for reaching it. So this measurement says nothing about
- the JavaScript-only shells (Türkiye Bursları, JASSO, Sciences Po's Eiffel page), where rendering
  was measured on 2026-09-14 to recover **zero** extra characters;
- rules stated only inside PDFs (DAAD's ST42 checklist extracts as Wingdings soup; Fulbright Nepal's
  `CV-Format.pdf` has never been opened);
- non-English and local-language pages, for which the corpus holds **no post-Soviet programme at
  all**;
- a university catalogue where one master's in fifty states a rule (TU Delft).

**Contamination, declared:** 2 of the 24 labelled URLs (`sciencespo-graduate`'s application-file page
and `fulbright-nepal`'s documents-required page) were themselves found via Firecrawl `/map` earlier
the same day while filling corpus gaps, so Firecrawl re-finding them is circular. Excluding both:
18 of 22.

## 4. Recommendation

Build. The subsystem's premise holds on the population we can currently score.

Two things to do first, in this order:

1. **Extend the corpus into the hard half** before trusting any headline number — post-Soviet and
   local-language universities above all, since that population is both absent from the corpus and
   the one the owner flagged. Until it exists, a good score means "good on consortia and funders".
2. **Add a second instrument for pages outside a host's link graph.** `daad-epos` proves enumeration
   alone has a hole with a shape: a rule page reachable only through a search form. Exa `/contents`
   with `subpages`/`subpageTarget` is the untested candidate already named in the design.

## 5. Addendum — the four "hard" classes, tested rather than assumed

Owner asked the obvious follow-up: are these actually unsolvable? Measured the same day. Two of the
four are already solved by decisions this repo has taken, and neither was noticed because the
evidence for "hard" predates those decisions.

**PDFs — solved.** Firecrawl `/scrape` returns DAAD's ST42 checklist as clean markdown, **5,255
characters and zero private-use glyphs**, with the rule intact as a table cell:

```
| CV
• format:EUROPASS,
• full CV without any unexplained gaps
• in reverse chronological order
• incl.the date of issue | □ mandatory
```

All four EPOS requirements, legible. The "Wingdings soup" recorded on 2026-09-17 came from **Tavily's
`/crawl`** rendering a PDF, not from the PDF. A PDF wants a scraper that knows it is a PDF.
*Consequence for the corpus:* the `daad-epos date_of_issue_required` row was marked `close_call`
only because its evidence was soup. That reason is gone.

**JavaScript-only — largely a stale label.** The `js_only` stratum was measured against
`readable_text`, this repo's own HTML reader, which the 2026-09-15 vendor decision then deleted.
Re-measured through Firecrawl:

| programme | our old reader | Firecrawl |
|---|---|---|
| turkiye-burslari (seed) | ~1,000 chars of 88,646 bytes | **6,581 chars of prose** |
| jasso (seed) | 265 chars | 1,688 chars — a thin navigation page, not a shell |
| czech-gov-scholarship (seed) | — | HTTP 500, unresolved |

Türkiye Bursları is not a shell; it was a reader problem, and the reader is gone. JASSO's seed is a
real but thin index page, which makes it a **discovery** problem — the content is elsewhere on the
site — consistent with CLAUDE.md's finding that its under-floor pages were retired URLs redirecting
to `/notfound.html`. **The strata labels in `cv-corpus-programmes.csv` now describe a fetcher that no
longer exists and should be re-derived before they are used to stratify any result.**

**Local-language — solvable, and the gap is narrower than "language".** Fetching is language-blind
and the models read Russian, Kazakh and Turkish. The real constraint is one regex:
`corpus.py::CANDIDATE_TERMS` matches `cv|curriculum vitae|résumé|lebenslauf|europass|özgeçmiş` — six
languages, and neither Russian (резюме) nor Kazakh (түйіндеме). A line-finder bound to a vocabulary
cannot find a line in a language it does not know. Which is the argument for putting those
programmes in the corpus: the corpus is how we learn which words are missing.

**One master's in fifty — the ladder already answers it.** Nobody crawls fifty programme pages. §1's
tiers mean a university is read **once** at institution level, and a programme page is read only when
that programme is itself a target. The cost is one page per programme a student is actually
recommended, not fifty per university.

**So the honest revision to §3's limits:** of the four classes named there, PDFs are solved, JS-only
is mostly a stale measurement, one-in-fifty is a design question already decided, and local-language
is a real gap with a small, identified cause. None of them is a reason not to build; all of them are
reasons the corpus needs the programmes it does not yet have.
