# CV-rule discovery — part 3 of the CV-requirement programme

**Status:** approved in conversation 2026-09-17, not built.
**Depends on:** part 1 (the labelled corpus and scorer, `claude/cv-corpus`, PR #99).
**Supersedes nothing.** It fills the tiers `apps/documents/constraints.py::_SCOPE_ORDER` already defines.

## What this is for

Find the CV requirements a programme publishes, and put them where the render can apply them.
Part 1 built the measuring stick — recall on BINDING requirements, `docs/research/cv-corpus-*.csv`
— and measured today's pipeline at **0.00 across the board**. This is the work that moves it.

## 1. The ladder, and what each tier may carry

The resolution order already exists and is not being changed:

```
UNIVERSAL  <  TRACK  <  COUNTRY  <  INSTITUTION  <  FUNDER  <  programme
```

(`constraints.py::_SCOPE_ORDER`, with programme rules applied last at the highest rank, and the
existing guard that an `ADVISORY_*` programme rule may not replace a `BINDING` one on the same key.)

What is new is a rule about **what each tier is allowed to hold**. This keeps being got wrong, and
the cost is asymmetric: a rule wrongly applied at a broad scope reaches every student under it.

- **COUNTRY holds conventions only.** `ADVISORY_*` only, never `BINDING`, and **never `language`.**
  All five seeded country rules already obey this — photos in Germany, photos and date of birth
  discouraged in the US/CA/GB/AU, German signature and gap tolerance — and none of them is about
  language. That was a judgement someone made and never wrote down.

  **Why it is not merely imprecise to generalise language to a country.** Most programmes publish
  no CV rules at all (§4). A country rule is overridden only when a more specific tier states
  something, so in the common case the country rule *is* the answer. Generalising "CVs here are in
  the local language" would not be a rarely-fired fallback; it would be the effective rule for
  every programme in that country, including the hundreds of English-taught master's programmes a
  German or Kazakh university runs, with nothing to correct it.

- **INSTITUTION holds a university's own CV guidance, read once per university** — not once per
  programme. TU Delft has roughly fifty master's programmes and one CV rule between them.

  Concretely, "once per university" means one enumerate-rank-read pass over the institution's host
  asking *does this institution publish CV guidance for applicants*, keyed on
  `Institution.canonical_key` (the `"<country>:<name>"` form `research/discovery.py::catalog_key`
  builds, which `constraints.py::_scope_matches` already matches on). It does not mean visiting each
  programme's admission page. A programme page is read only when that programme is itself a
  discovery target.

- **FUNDER holds funder and consortium rules.** This is where most real rules are (§4).

- **programme** (`Program.cv_format_requirement` / `cv_constraints` / `cv_directives`) holds only
  what the programme's own page states.

### CV language comes from the programme, not the country

`Program.teaching_languages` is an `ArrayField` the database requires to be non-empty and at most
ten entries (`apps/funding/models.py:478-483`). So every catalogue row already carries a
per-programme language fact, and it is a better default than the country the university sits in.

Order of preference:

1. An application language the programme states outright. The corpus already holds one:
   Eiffel's *"Resume in French or English (1 or 2 pages)"*.
2. `Program.teaching_languages`.
3. Nothing — and the CV says so.

**Stated gap, not to be quietly closed:** teaching language is the language the course is taught in,
which is not always the language the application is written in. A programme taught in English at a
French university may still want the file in French. So (2) is a *guess*, and it is shown to the
student rather than applied silently (§6).

## 2. When discovery runs

**In batches, launched by a person, as the `catalog_ingestion` role.** Not while a student waits.

This is not a preference; two things make the alternative impossible.

- **Row-level security refuses it.** Writes to the shared catalogue tables are restricted by
  Postgres policy to the `catalog_ingestion` role (`apps/funding/migrations/0006_official_snapshots.py`,
  `0018_catalog_rule_ingestion_write.py`, `0030_program_awarding_institutions_rls.py`). The web and
  worker processes run as the runtime role, so a search fired inside a student's session cannot
  persist what it finds — `derive.py::_write_program` raises `CatalogWriteBlocked` and says exactly
  this. The only ways round it are to grant the runtime role catalogue write, which lets one
  tenant's activity change what every other tenant reads, or to re-derive per student at six model
  calls a time and keep nothing.
- **A per-request URL is already barred.** CLAUDE.md, "LLM/AI security": profile only URLs reachable
  from an `OfficialSource` the catalog vouches for, never a URL supplied per request, because
  `ProgramStatement` is shared-catalogue data every tenant reads.

**A student who names a programme we do not hold is already handled, and needs nothing new.**
`apps/funding/services.py:144-178::consider_named_program` (reached by
`POST /student/recommendation/named-program/`, students only) creates a candidate marked
`CHECKING`/`eligible=False` and opens a **`ConsultantResearchTask`** — a human's queue, the same
§2.6 pattern the pipeline uses for blocked sources. The programme enters the catalogue through the
normal door and the next batch reads it. The student is never blocked: their CV generates from the
tiers below, and says so (§6).

**Refresh.** Yearly, riding part 6's refresh cadence, which the part 1 corpus spec already assumes
for re-pooling. Going from hand-run to scheduled is one EventBridge rule on the existing
`EuropassCanaryRule` pattern (`infra/template.yaml`) — the command does not change. It stays
hand-run until it has been watched across a few hundred programmes, because a timer means nobody is
watching the first time it misbehaves.

**Every batch carries a per-programme spend cap**, so one hard site cannot consume the month's
credits, and **reports what it could not read**. A page we failed to read must never be
indistinguishable from a programme that publishes nothing — the failure mode this repo has been
bitten by repeatedly.

## 3. Finding the pages: enumerate, rank, read

**This is a host-scoped job, and that is not what the provider probe measured.**
`docs/superpowers/research/2026-09-17-search-tool-probe.md` measured open-web funding *discovery* —
fire a query, count how many returned hosts award money — where Exa leads at 79% ORIGIN. Here we
already know the institution and its URL and need one page on that host. The probe says its own
open-web result does not transfer from the repo's earlier host-scoped finding; the converse holds
too. Do not cite the 79% in support of this design.

- **Enumerate** — Firecrawl `/map` (`limit` defaults to 5,000 and caps at 100,000;
  `includeSubdomains` already defaults true, which is what reaches `static.daad.de`) unioned with
  Tavily `/map`. Measured complementary 2026-09-15: together ~10-11 of 12 known rule pages,
  separately 8 and 6. Brave `site:` and Exa `/contents` are the host-scoped instruments of the two
  providers newly permitted (§7).
- **Target, before ranking — `Exa /contents` with `subpages` + `subpageTarget`.** Read from the docs
  2026-09-18 and not yet used anywhere in this repo: `/contents` takes 1-100 URLs and finds subpages
  matching a **semantic** term, up to 100 targets of 1-100 characters each. Exa's own documented
  example targets are `"admissions"` and `"requirements"` — this programme's exact question. It is
  the only vendor instrument that addresses the ranking problem below by meaning rather than by
  keyword, so it is worth measuring against our own ranker before we assume ours must do all of it.
- **Rank** — **ours, and this is the whole problem.** No vendor's relevance tells a university's
  careers office from its admissions page; on TU Delft and Leiden, Firecrawl's top hits are
  job-hunting advice, which is why both carry the `careers_decoy` stratum. Brave's Goggles are the
  one vendor feature that *is* this layer as configuration (`/scholarship$boost=2`,
  `$discard,site=mastersportal.com`) and took aggregators from 33% to 14% in the probe — worth
  copying as vendor-neutral code whether or not Brave is called. Host the Goggle rather than
  inlining it: one of twenty probe queries returned HTTP 422 on a long inline rule set.
- **Read** — Tavily Extract, unchanged. Measured equal to Firecrawl `/scrape`, and it reads DAAD and
  Sciences Po, which refuse this platform's address outright.

Two details worth carrying: Firecrawl's **`pdf` category** matters more here than the probe
suggested — DAAD EPOS states its CV rules in a checklist PDF and Fulbright Nepal in `CV-Format.pdf`,
and both are corpus rules we would otherwise miss. And Tavily's `include_domains` under
`include_domains_mode: "filter"` (300 domains max) restricts a search to the listed hosts, which
turns open search into site search for a university we already know — the code comment in
`search.py` currently reads "No includeDomains: nothing ever set it."

### Three traps in these endpoints, read off the docs 2026-09-18

- **Firecrawl `/map`'s `search` orders by words in the URL, not in the page.** Their own example:
  "'blog' will return URLs that contain the word 'blog' in the URL". This explains the otherwise
  unexplained 2026-09-15 measurement where the filter returned **zero** for i-mesc while unfiltered
  returned 76: a page at `/apply/documents` stating CV rules contains neither "cv" nor "curriculum"
  in its path. **So the ranker runs over the UNFILTERED inventory.** Firecrawl's relevance is a
  convenience for well-named URLs and must never be the ranking layer.
- **Tavily `/map` defaults `allow_external` to `true`**, exactly like `/crawl`. No `/map` client
  exists in this repo yet, so the trap is waiting for whoever writes one — pin it false there too.
- **Tavily `/map` with `instructions` costs 2 credits per 10 pages instead of 1.** Budget for the
  guided call being twice the unguided one, and prefer unguided enumeration plus our own ranker,
  which is the shape the first trap already forces.

**The crawl stays pinned to the seed's domain** (`tavily_crawl`, `allow_external: False`). Tavily
defaults it to true, and the first corpus pass followed DAAD's "use the europass template" link and
attributed 76 of that programme's 79 candidate sentences to Europass's own language picker.

**Do not import the funder-discovery configuration into this path.** The roster's measured settings
— Exa at `numResults: 100`, Brave paged to `offset` 9, local-language queries — are open-web recall
figures scored against a 377-funder answer key (`research/2026-09-17-search-capability-ablation.md`).
This job starts from a known host, where there is no long tail to page through and the query is not
a discovery query. The one rule that does carry over is negative and worth keeping: **never ask a
provider to filter by language** — Tavily's `language` cost 1.0 point and `filter_by_language`
another 1.3 on top. A Kazakh university's CV page may well be in Kazakh, and a language filter is
how we would lose it.

## 4. Where the rules actually are — and the sample that does not prove it

Counted over the 30 adjudicated dev programmes:

| type | programmes | publish CV rules | accepted rules |
|---|---|---|---|
| Erasmus Mundus consortium | 11 | 10 | 18 |
| Funder scheme | 13 | 6 | 14 |
| University | 6 | 2 | 3 |

Consortia and funders are where the rules are, and both are countable: the EACEA project API
returns all 415 EMJM projects in one POST (`apps/research/seeds.py:107-123`), so that half of the
population needs no search at all.

**This table must not be read as a reason to skip universities, and an earlier draft of this design
made exactly that mistake.** The six universities measured are FAU, Sciences Po, ETH Zurich, TU
Delft, Leiden and Aalto — all Western European, all admitting in English. The corpus contains **no
post-Soviet programme at all**, and all six programmes carrying the `non_english` stratum are
funders, not universities. So the table says nothing about a Kazakh or Azerbaijani university
requiring a CV in Russian or the local language, which is precisely the case the owner raised.

**Prerequisite before any coverage claim about universities:** extend the corpus with programmes
from the countries the product targets, adjudicated the way part 1's were. Note for whoever does it
that the probe found Exa alone returned `bolashak.gov.kz`, `dp.edu.az` and `addf.gov.az` — "exactly
the class the landscape research says has no index".

## 5. Giving the floor its rules

The ladder resolves correctly today and lands on almost nothing. **There are 27 seeded `CatalogRule`
rows in total: 17 FUNDER, 5 COUNTRY, 3 INSTITUTION, 2 TRACK, and 0 UNIVERSAL** — the three
INSTITUTION rows are `ai_use_policy` for Oxford, Cambridge and Edinburgh, nothing about CV format or
length. The universal tier is not empty, but it is close: `render.py::_UNIVERSAL_RULES` holds
**exactly one rule**, S-022's `min_final_page_fill`.

Meanwhile `docs/research/cv-rules.csv` (93 rules) and `cv-style-rules.csv` (33) hold researched,
sourced, tier-graded CV rules as **prose in CSVs**, enforced only where a human happened to cite one
in code. CLAUDE.md already records the consequence: "a new writer path inherits none of them by
default. That is how `evidence/extraction.py` came to write CV prose that obeyed no style rule for
weeks."

So part 3 has a second half, independent of discovery and buildable in either order: **give the
floor its rules.** Two corrections to an earlier draft of this section, both made by reading the
code rather than reasoning about it:

- **The universal tier is not seeded, on purpose — it is CODE.** `render.py::_UNIVERSAL_RULES`
  already implements it, and its comment gives the reason: a seeded rule depends on
  `manage.py seed_cv_rules` having been run by hand, and "a check that silently never fires is worse
  than no check, because the pre-flight then reports a clean CV either way". That judgement stands.
  The universal floor is extended **in that tuple**, not in `CatalogRule` rows — no migration, no
  command, no ordering dependency, and `resolve_rules` still lets any more specific catalog rule
  win, because `_with_universal_rules` appends only keys nothing has overridden.
- **It is 108 rules to adjudicate, not 126 to import.** 18 of the 126 already have a seeded row; the
  other 7 seeded ids (`C-002`, `L-021`, `L-024`, `L-025`, `L-039`-`L-041`) come from elsewhere. And
  `catalog_seed.py`'s own docstring puts the mappable share at about a third: "two thirds of the
  rules have no checkable key at all".

So the work is adjudication, not transcription, exactly as the corpus was: each of the 108 goes to a
`_UNIVERSAL_RULES` entry, to a scope-specific `CatalogRule` seed where it genuinely is
country-or-track-specific (obeying §1 — a national convention is `ADVISORY_*`, never `BINDING`, and
never `language`), or to an explicit unmappable list carrying the reason. **The deliverable that
makes this stick is a completeness test**: every `R-*` and `S-*` id in the two CSVs appears in
exactly one of those three places, so a researched rule can never again sit in a CSV with nothing
reading it — which is how `evidence/extraction.py` came to write CV prose obeying no style rule for
weeks.

This half is measurable on its own: it is the fallback arm of the corpus, and a programme that
publishes nothing should score against it.

**It also wants its own implementation plan.** Discovery (§2-4) and seeding the floor (§5) share
only the tier rules in §1; they touch different code, carry different risks, and neither blocks the
other. Planning them as one sequence would couple a crawl-and-rank problem to a research-transcription
problem for no reason.

## 6. The CV must say which rung it landed on

`generate_cv(programme=...)` degrades **silently** today. With no `ProgramStatement` rows, no
`cv_directives`, no `cv_format_requirement` and no `cv_constraints`, it renders and says nothing:
`generation.py:126-141` returns `None` from `_tailor`, `constraints.py:84-92` and `173-175` return
empty tuples, and `render.py:134-153::select_render_variant` falls back rather than raising, by
documented choice. A CV built from a programme's own published rules and one built because nobody
has ever read that programme are **the same render**, and nothing surfaces the difference.

One case makes it concrete: a programme with a blank requirement whose `country_code` is `DE` or
`AT` renders **`GERMAN_TABULAR`**, not standard (`render.py:51,151-152`). That may well be right,
but it is a formatting decision taken on no evidence and announced to nobody.

So discovery owes an outcome alongside the rules: **which tier answered**, carried into the render
warnings that `render_cv_with_warnings` already puts in front of the student. Under the glass-box
direction the student is the one who acts on it; "we read this programme's page" and "we used
general rules because we have not read it" are different facts and they must not look alike.

## 7. Providers and terms

**Owner decision, 2026-09-17: Exa and Brave may be used and their output stored, on the condition
that we are not training a search engine — which we are not.** This reverses CLAUDE.md's "Search
providers: what may be kept", which bars both by their own definitions (Brave: "Search Results"
means any API output, barred in whole or in part; Exa §4.2(a)). **CLAUDE.md and the probe document
must be updated in the same change that first calls either**, or the next session will re-apply the
old rule — it is written there in strong terms.

*Open:* the record should cite where that permission lives — an email, a support ticket, an order
form. Every other rule in this repo carries its evidence, and "owner states, 2026-09-17" is a weaker
anchor than a document.

Unchanged: Firecrawl stays discovery-only, so its silent terms never bind. Tavily remains the
retained-text path. **Perplexity: the Search API** (`POST /search`) — ranked results with no model
in the loop, `country`, `search_language_filter`, a 20-entry domain allow/deny list. Not Router (we
have OpenAI and Anthropic), not Embeddings (no vector store and no measured need), and not Agent: an
answer engine's prose is provider-derived content, and provenance comes from the origin. Note Sonar
chat completions sunset **27 September 2026**, and the Search API Addendum withdraws Output
ownership. **Diffbot: not needed** — its strength is an organisation knowledge graph, the
institution-safety screen was deleted on 2026-09-14 as not a product requirement, and EACEA already
returns the organisation roster.

## 8. What this delivers nothing without

**The recommendation pool does not read the catalogue.** `apps/research/services.py:90` still
fetches the hardcoded placeholder `https://official.example.test/program.json` and builds every
candidate from it; no `Program` query exists in that module. So rules discovered by part 3 sit in
the catalogue unused until the pool is connected to it.

That connection is not part 3's work. It is stated here so it is scheduled rather than discovered
late.

## Deliberately not built

- **On-demand discovery during a student's session.** Closed by RLS and the per-request-URL rule
  (§2), not by cost.
- **A provenance guard on catalogue rows.** Still absent (CLAUDE.md, "The institution-safety screen
  was removed"), still owed before a production search-key discovery run, and still not this spec's.
- **Per-programme crawling of every university master's.** Universities are read once at
  institution level; a programme page is read only when the programme is itself a discovery target.
- **Automatic country-level language rules.** §1. If a national convention is ever wanted, it is
  advisory, it is researched by a human, and it is not `language`.
