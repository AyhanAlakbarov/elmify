# A labelled corpus for CV-requirement discovery

**Date:** 2026-09-15
**Status:** approved by owner 2026-09-15; moving to implementation plan
**Scope:** part 1 of six. Parts 2-6 get their own specs.

## The problem this part solves

The goal is to find every CV requirement a programme or scholarship publishes, wherever it
lives, and apply it to the AI-written CV. The target is 99-100% accuracy. Today there is no
way to measure any of that: `docs/research/cv-format-eval.csv` scores a *judge* on 48
sentences handed to it, and the live reader test asserts that three reads of one page derive
the same rules. Neither answers "did we find the requirements this programme publishes".

Nothing can be built against an unmeasurable target, so the corpus comes first.

## What the number is for

A missed requirement and an invented one do not cost the same. **A missed binding
requirement — two pages when the funder said one, a photo where one is forbidden — costs a
student an application.** An invented one costs a needless edit the student sees in the
chatbot and can decline. So the corpus's headline number is **recall on BINDING requirements**,
and everything else is reported beside it rather than averaged into it.

That is what the number gates: whether the pipeline may apply a programme's rules to a
student's CV without a human between them. Below the floor, the rules are shown to the student
as findings and not applied. Parts 3 and 6 consume that gate; this part only produces it.

## What changed underneath this, and why it matters here

Owner decision, 2026-09-15: the research fetch path becomes vendor-supplied. **Tavily Extract
fetches and extracts; Tavily `/map` and Firecrawl `/map` are unioned for discovery; ranking
stays ours.** The Scrapling ladder, `BrowserTaskDefinition`, `LocalEgressProxy` on the
research path and `readable_text`'s section selection are all deleted in part 2.

Two consequences bind this spec:

- **The pipeline the corpus scores is not the pipeline that exists today.** The runner takes
  the pipeline as one injected seam rather than hard-coding today's call chain.
- **Reach stopped being the bottleneck; ranking became it.** Measured: Tavily reads DAAD and
  Sciences Po at 200, which our own stack cannot at all. But Firecrawl's map ranks TU Delft's
  *careers office* ("how to write a CV", CV workshops) above its admissions pages, and Tavily's
  map returns nothing whatsoever for five of eleven sites. So the strata are built around
  *finding and discriminating*, not around fetch failures.

## Decisions

| Question | Decision |
|---|---|
| Headline metric | Recall on BINDING requirements; all else reported alongside. **Owner-confirmed as the gate** for applying rules to a CV without a human between them |
| Scoring unit | Per rule: recall and precision |
| Ground truth | Pooled from several independent methods, then human-adjudicated |
| Labelled unit | Two layers — the verbatim sentence **and** the normalized requirement it yields |
| Population | Stratified by failure mode, with a held-out third |
| Adjudicator | Claude adjudicates; owner reviews a random 20% sample and every close call |
| Size | 45 programmes now; grow toward 120 later |
| Lifetime | Re-pooled automatically every cycle for every programme in the database; changed rows re-adjudicated by a human |
| Storage | Two CSVs in `docs/research/`, matching the existing catalog pattern |
| Runner | A `live`-marked pytest, excluded from a default run by the existing `addopts` |

## The artifact

### `docs/research/cv-corpus-programmes.csv`

One row per programme.

| Column | Meaning |
|---|---|
| `id` | Stable slug, e.g. `fau-ai-msc`. Referenced by the rules file. |
| `institution` | Awarding or hosting institution. |
| `funder` | Funder where the pair matters, else empty. Rules attach to the **(institution, funder) pair**, not the funder alone — measured: Campus France says nothing about the CV while Paris-Saclay, an Eiffel host, specifies "1 or 2 pages, following the example". |
| `seed_url` | The one URL the pipeline is given. **Always the programme's own front page as a student would land on it from a search — never a documents, requirements or FAQ page.** Seeding with the rule page defines the discovery problem away, which is the same trap as the rejected fixed-page-list approach. |
| `admissions_cycle` | Requirements are per cycle; a label is only true for one. |
| `expected_outcome` | `found`, `no_cv`, `blocked`, `not_found` — the four outcomes part 3 must report. This is what makes the `no_cv` stratum scorable at all (below). |
| `strata` | Semicolon-separated flags, below. |
| `split` | `dev` or `heldout`. 30 and 15. |

### `docs/research/cv-corpus-rules.csv`

One row per labelled rule.

| Column | Meaning |
|---|---|
| `programme_id` | FK to the programmes file. |
| `source_url` | The page, PDF, DOCX or archive entry the sentence is on. |
| `source_sha256` | Digest of **our own Tavily extract** of `source_url` at label time. What drift detection compares against. |
| `sentence` | Verbatim, as published. The localization layer. |
| `requirement_key` | One of the **existing** vocabulary, below. |
| `requirement_value` | Normalized value, e.g. `2`, `europass`, `false`, `en`. |
| `enforcement` | `BINDING`, `ADVISORY_HIGH_RISK`, `ADVISORY_STYLE` — the existing `Enforcement` enum. Decides which recall the row counts toward. |
| `status` | `accepted`, `rejected`, `close_call`. |
| `adjudicated_by` | `claude` or `owner`. |
| `pool_source` | Which pass surfaced it (`pipeline`, `vendor_agent`, `hand`, `post_hoc`). Needed to know what the pool would have missed without each pass. |
| `note` | Why, for anything not self-evident. |

**The vocabulary is the one already in the code, not a new one.** `requirement_key` is a
member of `_CONSTRAINT_KEYS` (`apps/documents/constraints.py`), or `cv_format_requirement` /
`cv_directives` (`Program`). A requirement the vocabulary cannot carry is recorded under the
key that already exists for exactly that — **`unapplied`**, "states a CV requirement that
names no field, section or key this engine has" — with the sentence kept. An earlier draft
invented `unexpressible`; it was a duplicate. A key genuinely missing from the engine is a
finding to raise, made by adjudication and added to code and corpus at once.

**Duplicates across languages and sources collapse at the requirement layer and not at the
sentence layer.** The Eiffel CV template is linked from both the French and English pages;
that is two sentences and one requirement. This is precisely why the two layers exist.

## The strata

Chosen from the failure modes the site survey actually measured, not from a taxonomy.

| Stratum | Why it is in the corpus | Known example |
|---|---|---|
| `blocked` | Our own address is refused; the page is reachable only through the vendor path. Since Tavily reads these, this stratum is a **regression guard on the vendor decision**, not an accuracy stratum | DAAD, Sciences Po |
| `js_only` | Server HTML is a shell; prose is rendered client-side | Türkiye Bursları, JASSO |
| `in_template` | The rule is inside a linked DOCX/PDF/ZIP, not in any page text | SISGP `.docx`, Fulbright Nepal PDF, Eiffel template |
| `deep` | The rule is two or more hops from the seed | ETH, Stipendium Hungaricum |
| `careers_decoy` | The site has a careers-office CV page that outranks the admissions one | TU Delft, Leiden |
| `no_cv` | The programme genuinely requires no CV — zero is a real answer | Chevening, GKS |
| `non_english` | The rule is published in another language | DAAD German docs, Eiffel French page |

Every programme carries zero or more flags; one with none is a control, so the pipeline's
score on an ordinary site is visible beside its score on the hard ones. `careers_decoy` and
`no_cv` are the two that no
amount of fetch engineering helps with, and are deliberately over-represented relative to
their real-world frequency: they are where the remaining accuracy lives.

**Contamination rule.** The 12 pages in `cv-format-eval.csv` and the 18 sites of the 2026-09-15
survey were all chosen, in part, because they were findable, and the judge was calibrated on
the former. They may go in `dev`. **None of them goes in `heldout`.**

## Building the ground truth

For each programme, three independent candidate passes:

1. **The pipeline as it stands** — whatever parts 2-4 have produced at that date.
2. **A vendor crawl with instructions** — Tavily crawl by default, because its output may be
   retained under terms already cleared; Firecrawl `/agent` only where Tavily's crawl returns
   nothing, which it did for five of eleven sites in the probe. Its pricing is dynamic and can
   exceed the free tier on one hard site, so its use is logged per programme.
3. **A deliberate hand search** — reading the site the way an applicant would.

Every `(source_url, sentence)` pair from all three is pooled and deduped. Each pooled
candidate is then adjudicated on four questions:

1. Is the sentence on that page, verbatim — **verified against our own Tavily extract of the
   page**, never against the vendor agent's output? This is what keeps pass 2 inside the
   pointer rule: what is retained is the institution's sentence, found via a vendor, not the
   vendor's reading of it.
2. Is it a CV requirement **for this programme** — not careers advice, not another
   programme's rule, not marketing copy on the same domain?
3. What normalized requirement does it yield, if any?
4. Is it binding or advisory, in the programme's own wording?

Question 2 is the one that is not mechanical, and it is exactly the discrimination the whole
project turns on. Anything not obvious is marked `close_call` and goes to the owner along
with a **random 20% sample of the accepted rows**, which is what calibrates the adjudicator.
If the owner overturns more than one row in twenty, the adjudication is redone by the owner
and the sample is raised rather than the disagreement being split.

**Independence is weaker than three passes sounds.** Pass 1 is the pipeline, pass 3 is Claude
reading, and the adjudicator is Claude. Only pass 2 is a genuinely different reader. This is
why the owner sample is not optional and why pass 2's misses are tracked separately via
`pool_source`.

**Unjudged system output is adjudicated, never counted wrong.** When a later pipeline reports
a requirement not in the pool, it is a candidate: adjudicated, added with
`pool_source = post_hoc`, and only then scored. Counting it as a false positive would punish
the pipeline for finding a real rule the pool missed. On the held-out set, post-hoc rows are
adjudicated by the owner only, so the set's integrity rests on one reader who is not being
scored.

**Stated limit, accepted when the approach was chosen:** recall is measured against the pool.
A requirement no method found is invisible to this corpus and will read as a perfect score.
This is standard practice in retrieval evaluation and it is a real ceiling, not a formality.

## Scoring

Over the **requirement** layer:

- **Binding recall** (headline) = accepted BINDING requirements the system reported / all
  accepted BINDING requirements.
- **Recall** and **precision** over all accepted requirements, reported beside it.

Over the **sentence** layer, reported as **localization**: for each accepted requirement, did
the system's stored statements for that programme include a sentence from any `source_url`
carrying that requirement (URL-normalized; either language variant counts). This is the split
that says whether a loss came from discovery or from derivation — without it a single number
cannot tell a crawler bug from a judge bug.

Over the **programme**: did the reported outcome match `expected_outcome`. This is the only
metric that is defined for a `no_cv` programme, where the requirement set is empty by
construction and recall has no denominator. A `no_cv` programme scored `not_found` is a
failure of honesty, not of coverage, and it is the failure the four-outcome design exists to
surface.

**Per-stratum reporting is on `dev` only.** Fifteen held-out programmes across seven strata is
about two per stratum, and a per-stratum number at n=2 is noise dressed as diagnosis. The
held-out set reports binding recall, overall recall/precision, localization and outcome
accuracy — in aggregate — and nothing finer.

The held-out set is not scored until a part is declared finished.

## The runner

`tests/research/test_cv_corpus.py`, marked `live`, so `pyproject.toml`'s existing
`addopts = "-m 'not live'"` keeps it out of a default `pytest` run — the same arrangement the
reader and judge live gates already use.

It reads both CSVs, runs the pipeline through a single injected seam, prints the per-stratum
table for `dev` and the aggregate for `heldout`, and asserts floors that live as constants at
the top of the test file and are ratcheted by hand as each later part lands. A ratchet is a
reviewed code change on purpose. The printed table is the artifact a human reads; the
assertion only stops a regression.

Before scoring, it re-extracts each `source_url` and compares against `source_sha256`. A
mismatch is printed as drift and the row is excluded from that run's denominator, never
silently kept or silently dropped.

## What this part deliberately does not do

- **It does not score the produced CV.** Whether the generated document complies is part 6.
  Mixing it in here would confound discovery errors with writing errors.
- **It does not go in the database.** CSVs are reviewable in a diff, survive schema churn, and
  need no migration — and this file's whole value is that a human can audit it.
- **It does not re-adjudicate automatically when a page changes.** Drift is flagged for a
  human, never relabelled by a model.
- **It does not attempt 99%.** See below.

## The measurement ceiling, stated plainly

45 programmes at roughly four rules each is 180-250 labelled rules, of which binding ones are
a fraction. At n=200, a 99% reading carries a confidence interval of about ±1.4%, so 97.5% and
100% are the same measurement — and on the binding subset alone the interval is wider still.

**This corpus can honestly demonstrate ≥95% and can diagnose where the losses are.** That is
what parts 2-4 need from it. Demonstrating 99% needs closer to 500-1000 labelled rules —
roughly 120 programmes. Owner decision: build 45 now, grow later.

**Growing is not cheap, and an earlier draft implied it was.** Parts 2-3 automate pass 1, but
pass 3 and adjudication are the expensive steps and neither is automated by anything planned.
Extension is linear in adjudication time. What the first 45 buy is the tooling and the
calibrated adjudicator, not a discount on the next 75.

## Cost and lifetime

**Credits.** Tavily Extract at `advanced` depth is 2 credits per URL; map and crawl are priced
per page. Three passes over 45 programmes at perhaps 20 pages each is on the order of 3,000
Tavily credits for the initial build plus a Firecrawl `/agent` spend that cannot be bounded in
advance on the sites where it is needed. Both keys already exist. The runner's drift check is
one extract per labelled row per run, roughly 200-250 credits, which is why it is `live` and
not in the default suite.

**Lifetime — owner decision 2026-09-15.** Every label is true for one `admissions_cycle`.
When the cycle turns, the corpus is **re-pooled automatically for every programme in the
database**: the drift check runs, the candidate passes re-run, and every row whose source
changed or whose requirement moved is queued. That is the same yearly cadence part 6 gives
the production catalog (full search once per cycle, cheap change check monthly), and the
corpus rides on it rather than having its own schedule.

What is *not* automated, and cannot be without destroying the corpus: **the labels
themselves.** A machine that relabels the ground truth scores the machine against itself.
So the yearly run produces a diff — rows unchanged, rows drifted, candidates new — and the
human step shrinks to adjudicating the diff rather than relabelling from scratch. The 20%
owner sample applies to the re-adjudicated rows exactly as it did to the originals.

Practical consequence: the corpus grows with the database. Every programme added to the
catalog gets pooled on the next cycle run and becomes a candidate corpus row; the
adjudication queue is what bounds how many become labels. This is how "45 now, 120 later"
happens without a separate labelling project.

## A correction this spec carries

CLAUDE.md states in two places that a counsellor sees `undecided` rules and warnings beside
the quote, and `apps/documents/constraints.py` says the same in its own comments on
`undecided` / `unapplied` ("so the counsellor reads the page's own words"). **That is not the
product.** No counsellor reviews CVs: the AI writes the CV, the student sees it, and changes
are made through a planned chatbot. The `undecided` and `unapplied` rows still exist and are
still the right design — a rule nothing can act on must be shown rather than dropped — but
their audience is the student, through that chatbot, and the surface does not exist yet.
Part 6 owns it. The CLAUDE.md wording and those code comments are corrected as part of this
part's work, because a spec that builds on a false statement of who reads the output will
get the output wrong.

## Risks

- **Pool blindness.** Accepted, stated above. Mitigation is the diversity of the passes, not a
  guarantee — and see the independence caveat: the diversity is smaller than three.
- **Corpus staleness.** Live pages in a live cycle. Mitigated by `source_sha256` per row, a
  loud drift exclusion, and the yearly automatic re-pool — never by re-labelling
  automatically. The human step is the adjudication of the diff.
- **Adjudicator bias.** Claude adjudicates the bulk and Claude is also being scored. The owner
  sample and the owner-only rule for held-out post-hoc rows are what make this tolerable.
- **Vendor coupling.** Pass 2 uses a vendor crawl. If the vendor changes behaviour, the pool
  changes and historical recall numbers stop being comparable. `pool_source` plus the vendor
  and date of each pooling run are recorded so the comparison can at least be qualified.
- **Held-out erosion.** Every post-hoc addition to the held-out set is a look at it. The
  owner-only rule limits who looks, not whether. If the held-out set accumulates many post-hoc
  rows, it has become a second dev set and should be said to have.
