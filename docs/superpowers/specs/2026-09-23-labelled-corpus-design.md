# The labelled corpus — the instrument every gate reads

Design, 2026-09-23. Owner decisions the same day: **the corpus is tiered, not flat** — four
languages deep enough to tune a threshold, thirteen shallow enough to detect a broken one; and
**labelling is a command, not a text file** — code enumerates a page's sentences and a person ticks
ids.

This is part 1 of the corpus work named in `2026-09-22-typed-decisions-and-multilingual-sources-design.md`
§11 ("its own spec") and `2026-09-22-fetch-engine-design.md` §13 ("the labelled corpus's live
discovery gate (its own spec)"). It builds nothing that decides anything in production: the corpus
is an instrument, and an instrument that changes what ships is a bug in the instrument.

Read with: typed-decisions §4 (the decision table), §8 (the multilingual layer), §11 (the thirteen
gates); fetch-engine §7.0 (the funnel and its stop rule), §13 (the gates).

---

## 1. Why this exists

Seven of the thirteen gates in typed-decisions §11 — 3, 5, 8, 10, 11, 12, 13 — have no data. They
are written, they skip, and they will keep skipping until something tells them what the right answer
was. That something is this corpus. Two consequences follow, and both are already written into the
plans:

- **No non-English decision has been measured by anyone**, including the vendor (typed-decisions
  §3.1 item 8). The design's answer is §11.3: a language below the bar has every decision in it
  written as a note rather than acted on. That rule is only reachable if a number exists per
  language, and the number comes from here.
- **The funnel's stop rule is only as good as D3's `documents-list` kind** (fetch-engine §7.0). A
  stop rule scored on recall alone looks perfect while stopping on the wrong page every time. The
  count that catches it — the *false stop* — needs a human who knows which page really carried the
  programme's requirements.

The failure this corpus exists to prevent is the one this repo has now made in three designs: a
read that returns nothing and a page that says nothing are indistinguishable from the outside, so a
measurement that only counts what was found reports success on silence. Every score below is
therefore paired with its negative.

## 2. Scope and non-scope

**In scope:** the labelled data, the command that produces it, its counts, where the pages come
from, how drift is detected, and which gate reads which field.

**Not in scope:** the gates themselves (written in
`docs/superpowers/plans/2026-09-23-reader-and-multilingual-layer.md` Task 11 and
`docs/superpowers/plans/2026-09-23-site-jobs-and-the-funnel.md` Task 13); thresholds (the corpus
sets them, this spec does not name them); the vocabularies of typed-decisions §8.1, which are
drafted by a model and reviewed separately.

**Deliberately not a training set.** Nothing here is fed to a model as an example, fine-tuned on,
or embedded. Exa and Brave's written permission carries one condition — no competing-search
training (CLAUDE.md) — and TypeSafe's MCA §2.3 bars distillation. A labelled corpus is exactly the
artefact someone reaches for when they want to train something. It is for scoring, and §12 records
what would have to change first.

## 3. Two layers, because there are two consumers

The corpus has two consumers with different units, and merging them would make one of them wrong.

| layer | unit | question it answers | consumer |
|---|---|---|---|
| **page** | one fetched page | which sentences on this page state a requirement, and what is each one? | typed-decisions §11 gates 3, 5, 8, 10, 11, 12, 13 |
| **programme** | one programme | which URLs carry this programme's requirements? | fetch-engine §13, the funnel's stage scoring and false-stop count |

They share pages — a programme's requirement URL is a page record — and the programme layer is
**generated from the page layer plus a programme index**, never maintained by hand. A URL labelled
in two places drifts, and a corpus that disagrees with itself scores nothing.

### 3.1 The page record

One file per page: `docs/research/corpus/page-<slug>.json`, where `<slug>` is
`<host-without-dots>-<path-slug>` truncated, unique within the directory.

```json
{
  "url": "https://www.example-univ.de/msc-ai/bewerbung/",
  "final_url": "https://www.example-univ.de/msc-ai/bewerbung/",
  "fetched_at": "2026-09-30T09:14:22Z",
  "content_sha256": "3f2a…",
  "language": "de",
  "page_kind": "documents-list",
  "page_is_real": true,
  "belongs_to_programme": true,
  "page_text": "# Bewerbung\n- Lebenslauf (max. zwei Seiten)\n…",
  "statements": [
    {
      "id": 7,
      "text": "Lebenslauf (max. zwei Seiten)",
      "document": "cv",
      "kind": "DOCUMENT",
      "requirement": "REQUIRED",
      "third_party": false,
      "conditional": false,
      "negated": false,
      "slots": {"operation": "limit", "value": {"limit": 2, "unit": "pages"}, "scope": "applicant"}
    }
  ],
  "labelled_by": "owner",
  "labelled_at": "2026-09-30",
  "notes": ""
}
```

Field by field, and what reads it:

- **`url`, `final_url`, `fetched_at`, `content_sha256`** — the page's identity and its drift
  detector (§7). `final_url` is the engine's, after `require_same_origin`.
- **`language`** — BCP-47 with script where the script matters (`kk-Cyrl`, `kk-Latn`, `uz-Latn`,
  `zh-Hans`), the same vocabulary `ProgramStatement.language` uses (typed-decisions §8.2). Every
  per-language score groups on this. It is a **label**, not D1's answer: D1's language Choice is
  scored *against* it.
- **`page_kind`** — one of D3's six: `programme`, `how-to-apply`, `documents-list`, `funder-award`,
  `faq`, `other`. Gate 5's triage recall and the funnel's false-stop count read it.
- **`page_is_real`** — false for a soft 404, an anti-bot interstitial, a region selector or a shell
  (D1's four Nouls). A corpus with none of these cannot score D1, and the soft 404 is not
  hypothetical: three JASSO URLs redirect on-origin to a 52,998-byte `/notfound.html` that passes
  `require_same_origin` and archives as the page (CLAUDE.md).
- **`belongs_to_programme`** — false for a faculty-wide page, another programme's page, or a
  generic university admissions page. This is the false-stop label.
- **`page_text`** — the readable extraction (`reader.readable_text` for a selected page, or
  `reader.page_lines` joined), **not** raw HTML, and it is stored because it is what the splitter
  takes. Storing the HTML instead would mean every gate re-runs the extractor and scores it by
  accident.
- **`statements`** — every sentence a person marked. `id` is the index into
  `sentences.page_sentences(page_text)`; `text` is that sentence verbatim. **Both are stored and a
  test asserts they agree** — the id is what the command wrote, the text is what a human can read in
  a diff, and if the splitter changes they stop agreeing, which is the point (§7).
- **`document`** — `cv`, `motivation_letter`, `reference_letter`. Replaces the plan's per-kind file
  glob (§9.1).
- **`kind`, `requirement`** — `ProgramStatement.Kind` and `.Requirement` exactly:
  `COMPETENCY | DOCUMENT | FORMAT | LANGUAGE | OTHER`, `REQUIRED | DESIRED`. Gate 3's recall and
  gate 10's label accuracy read these.
- **`third_party`, `conditional`, `negated`** — the three sentence-level negatives (§5.2). They are
  properties of a *labelled* sentence rather than separate records, because that is where they
  occur: "Short CV (max. 2 pages) from this academic supervisor" is a real requirement sentence
  that D5 must not attribute to the applicant, and two of three frontier readings did exactly that
  (CLAUDE.md).
- **`slots`** — the four-slot grammar's expected answer (typed-decisions §6.1), filled only where
  the person is confident. Gate 8's unapplied rate needs the *denominator* (every requirement
  sentence) and not every numerator, so a missing `slots` is legal and counted separately from
  `operation: other`.

### 3.2 The programme record

`docs/research/corpus/programmes.json` — one list, generated:

```json
[
  {
    "source_url": "https://www.example-univ.de/msc-ai/",
    "admissions_cycle": "2027",
    "language": "de",
    "requirement_urls": ["https://www.example-univ.de/msc-ai/bewerbung/"],
    "document_urls": ["https://www.example-univ.de/msc-ai/checkliste.pdf"],
    "decoy_urls": ["https://www.example-univ.de/bewerbung/"]
  }
]
```

- **`requirement_urls`** — the exact set, which is what the funnel is scored against. A stage that
  finds a URL outside this set found something the corpus does not vouch for; a run that finds none
  of them is a miss.
- **`document_urls`** — linked PDF/DOCX/ZIP the requirements actually live in. Stage 1 exists for
  these and is scored separately, because a funnel that never reaches a linked checklist looks
  identical to one whose programme has no checklist.
- **`decoy_urls`** — pages with `belongs_to_programme: false` that a crawl will plausibly reach: the
  faculty's generic admissions page, the university-wide "how to apply". **A stop on one of these is
  the false stop.** Without decoys the false-stop count is structurally zero and the stop rule
  scores perfect.

**Keyed on `(source_url, admissions_cycle)`, not `program_id`.** A UUID committed to the repository
means nothing in a database where that `Program` row does not exist, which is every machine but the
one that wrote it. `score_funnel` joins `SiteJobRecord.source_url` instead — it already carries it
(§9.2 records the one-line plan change).

## 4. Labelling is a command

`manage.py label_page <url> [--cycle 2027] [--document cv|motivation_letter|reference_letter]`.

1. Fetches the URL through the engine's own ladder (`retrieve_official_source`), so the corpus page
   is a page the engine can actually reach — a corpus of pages fetched some other way scores a
   fetcher we do not ship.
2. Runs `readable_text` / `page_lines`, then `sentences.page_sentences`, and prints the numbered
   sentences under their heading path.
3. Asks, per page: language, `page_kind`, `page_is_real`, `belongs_to_programme` — each a pick from
   the closed list, never free text.
4. Asks, per ticked id: `document`, `kind`, `requirement`, the three negative flags, and optionally
   the four slots — again picks, not typing.
5. Writes `page-<slug>.json` and appends to `programmes.json`.

**Why this and not a CSV.** The original brief was "rule + exact URL + verbatim quote". A quote
typed by a person is a quote no splitter necessarily emits — one different space, one soft hyphen,
one line the extractor joined — and it then scores as a permanent miss that no amount of model
improvement can fix. Ticking an id makes every label a sentence the splitter really produced, by
construction, which is the same guarantee `verified_statements` was built to give and the same
reason it could be deleted. It also turns roughly an hour a page into roughly ten minutes, which is
the difference between 92 pages happening and not happening.

**The command is the only writer.** Hand-editing a corpus file is permitted for the `notes` field
and nothing else; a test asserts every `statements[].text` equals
`page_sentences(page_text)[id]`, so a hand-edit that drifts fails loudly rather than scoring
silently.

**It is not a review queue.** No person is in the production pipeline (owner decision 2026-09-23);
this command is a build-time tool run deliberately, like `manage.py funding_review`, and nothing
schedules it.

## 5. Size and composition

### 5.1 Two tiers

The bar that sets the size is gate 3: recall ≥ 0.95 per language. One miss in twenty is 0.95, so a
bucket with fewer than twenty labelled requirement sentences cannot distinguish 0.95 from 1.00 and
its number is decoration.

| tier | languages | floor |
|---|---|---|
| **1 — tuned** | `en`, `de`, `tr`, `ru` | ≥ 40 labelled requirement sentences and ≥ 10 pages per language |
| **2 — screened** | `fr`, `az`, `kk-Cyrl`, `kk-Latn`, `uz-Latn`, `ky`, `tk`, `ka`, `hy`, `mn`, `zh-Hans`, `ja`, `ko` | ≥ 20 labelled requirement sentences and ≥ 4 pages per language |

**Pages are whatever it takes to meet the sentence floor**, never the other way round: a checklist
page yields fifteen requirement sentences and a prose page yields two, so counting pages measures
the pages and not the language.

About 92 pages in total, of which 28 are negatives (§5.2). Tier 1 is four languages because those
are where a wrong decision ships today — English and German carry the programme pages already in
this repo's measurements (FAU, TUM, DAAD PRIME, SISGP, Rhodes), Turkish and Russian carry the
origin-country funding pages the fourteen-language vocabulary exists for.

**Tier 2 is explicitly not enough to tune a threshold, and that is the design.** Twenty sentences
tells you whether a language is broken, not where its bar should sit. Until a tier-2 bucket is
raised to tier 1, §11.3 applies to it by default: its decisions are written as notes (§6.4), not
acted on. That is the rule degrading gracefully, not a gap — and it is why "we shipped fourteen
languages" must never be said on the strength of this corpus.

### 5.2 Negatives, counted

Gate 11 requires negatives "in every language" and says this spec fixes the counts. Five kinds,
three of which are sentences inside otherwise-positive pages:

| negative | unit | tier 1 floor | tier 2 floor |
|---|---|---|---|
| page states no CV or letter rule | page | 2 per language | 1 per language |
| page is not the programme's (a decoy) | page | 1 per language | — (the shared decoy set) |
| page is not a real page (soft 404, challenge, selector, shell) | page | ≥ 6 across the whole corpus | — |
| third-party sentence (referee, supervisor, host, employer) | sentence | 5 per language | 1 per language |
| negated or conditional sentence | sentence | 5 per language | 1 per language |

The first two are the 28 negative pages. The last two are flags on sentences already labelled; if a
language's pages happen to contain none, one more page is added that does — not a sentence
invented, because an invented sentence scores an invented failure.

**The not-a-real-page floor is corpus-wide, not per language**, because there are only so many of
them and they are all the same phenomenon. Six is the number of distinct shapes measured in this
repo: JASSO's soft 404, Türkiye Bursları' shell, Sciences Po's short-real-page, a Cloudflare
interstitial, a region selector, a cookie wall.

## 6. Where the pages come from

- **Real pages only, fetched through the engine.** No synthetic page, no page a person wrote to
  make a point. A corpus of pages we constructed measures our imagination.
- **Sources already in the repo's measurements first**, so old numbers stay comparable: FAU AI
  M.Sc., TUM Informatics, DAAD PRIME, SISGP, Rhodes, JASSO, Türkiye Bursları, Sciences Po, the 58
  EACEA hosts of the funding-yield run.
- **`docs/research/cv-format-eval.csv`'s 48 sentences are not re-labelled into this corpus.** They
  are gate 1's own set, they already have their answers, and copying them in would make gates 1 and
  12 share data and stop being independent.
- **Tier-2 languages come from the funding-led discovery sources** the specs already name — Korea's
  `academyinfo.go.kr` catalogue, Finland's `konfo`, and the origin-country ministry pages the
  fourteen-language vocabulary was drafted for.
- **One page per host, unless the host is a tier-1 language's only source.** Ten pages from one
  university measures that university's CMS.

## 7. Drift, and how it is caught

A corpus of live pages rots. Three mechanisms, in order of how loudly they fail:

1. **`content_sha256`.** `manage.py check_corpus` refetches every page and reports which changed.
   It is a report, not a failure: a changed page is normal, and the question is only whether its
   labels still hold. A changed page is re-labelled or dropped, by a person, and the file records
   which.
2. **The `id`/`text` agreement test** (§3.1). It fails in CI the moment the splitter changes
   behaviour on a corpus page — which is exactly when every recall number silently shifts. This is
   the one that must be a hard failure, because a splitter change is a *code* change and the corpus
   is how we notice it moved the floor under every gate.
3. **`labelled_at`.** A page older than one admissions cycle is flagged by `check_corpus`. Programme
   requirements change yearly; a 2026 label on a 2028 page is wrong in the direction that looks
   like a model regression.

**The page bytes are not committed; the extraction is.** `page_text` is in the file, raw HTML is
not. It keeps the corpus small (≈ 1 MB), and it is the same standing `ProgramStatement` already has
— verbatim sentences from a third-party page, stored because they are the record of what the page
said.

## 8. Standing — legal and privacy

- **Every page is a public programme or funder page. No student text is in the corpus, ever.** This
  is what lets the corpus go to Jev *now*, before the DPA: `docs/legal/2026-09-provider-terms.md`'s
  status line bars real student text, and public page text has the same standing it already has
  when it goes to OpenAI or Anthropic today.
- **No provider result object is persisted.** A URL reached through Exa or Tavily is fetched from
  the origin and the origin's bytes are what get labelled — the rule CLAUDE.md states for search
  providers, applying unchanged here.
- **Nothing in the corpus is derived from a person.** It never points at `audit.Pseudonym` because
  it has nothing to point with; it is not a derived-data table and the §6.1 ML rules do not reach
  it.

## 9. What each gate reads, and two plan changes this forces

### 9.1 The gate map

| gate | reads | fails on |
|---|---|---|
| 3 — per-language recall and label accuracy | `language`, `page_text`, `statements[].text/kind` | a language below 0.95 recall or 0.9 accuracy → every decision in it is a note |
| 5 — triage recall | `page_kind`, `page_is_real` | a rule-bearing page that does not clear D3 |
| 8 — unapplied rate | `statements` (denominator), `slots` (numerator) | `operation = other` above 2% per language → the grammar grows first |
| 10 — letter selection | `statements[].document == motivation_letter \| reference_letter` | same bars as gate 3 |
| 11 — negatives | `page_is_real`, `belongs_to_programme`, `third_party`, `conditional`, `negated`, the no-rule pages | a false positive rate nobody measured |
| 12 — wording ablation | the whole page layer, run per wording | the shipped wording is the one that won, per language |
| 13 — state ablation | the whole page layer, run per chunk size and state shape | the shipped chunk is the one that won |
| fetch-engine §13 — funnel | `programmes.json` entire | a stage that never finds a page earlier ones missed is removed; a stop on a decoy is a false stop |

Gates 1, 2, 4, 6, 7 and 9 do not read the corpus: 1 has `cv-format-eval.csv`, 2 has the six pages
with stored statements, 4 and 9 read `DecisionRecord` history, 6 is repeats on one page, 7 is the
216 catalogued rules.

### 9.2 Two changes to plans already written

Both are small, both are in plans not yet executed, and both are here because the corpus's shape
decided them:

1. **`tests/research/test_language_gates.py` globs `{kind}-*.json`** — a separate file per document
   kind. A page stating both a CV rule and a letter rule would then exist twice and drift. Change
   `_pages(kind)` to read every `page-*.json` and filter on `statements[].document`, which is one
   line and removes the duplication.
   (`docs/superpowers/plans/2026-09-23-reader-and-multilingual-layer.md` Task 11.)
2. **`score_funnel --corpus` joins on `program_id`** — a UUID that only resolves in the database
   that wrote it. Join on `SiteJobRecord.source_url` + `admissions_cycle` instead, which the record
   already carries.
   (`docs/superpowers/plans/2026-09-23-site-jobs-and-the-funnel.md` Task 13.)

## 10. Cost

- **Building it:** ~92 pages at ~10 minutes each with the command, so on the order of two working
  days of a person's attention, spread. Without the command, on the order of two weeks.
- **Fetching it once:** 92 pages through the ladder at 1–2 credits each, ≈ $0.15. Negligible, and it
  happens again on every `check_corpus` run.
- **Running a gate:** the page layer is offline text, so a gate costs only its decision calls —
  typed-decisions §10 prices D1+D3+D4+D5+D6+D8 at ≈ $0.001 per page, so a full sweep of the page
  layer is ≈ $0.10. Gates 12 and 13 multiply that by the number of wordings and chunk sizes, so
  budget ≈ $1 for a full ablation round.
- **The funnel gate is the expensive one:** it runs real discovery, at 2–25 ¢ per programme per
  stage, `maxConcurrency: 1`, N runs recorded. At 20 programmes × 4 stages × 3 runs ≈ $15–20 a
  round. It is the only part of this spec that needs a spending decision, and it is why the funnel
  gate runs on a *subset* of the programme layer, named in the file.

## 11. Deliberately not built, with the trigger

- **A second labeller and an agreement figure.** One person labels everything, so inter-annotator
  agreement is unmeasured and every score carries that. **Trigger:** a gate failing in a way that
  looks like a labelling disagreement rather than a model error — the first time someone argues with
  a label, two people label a 20-page overlap and the κ goes in the file.
- **Native-speaker review of tier-2 labels.** Same shape as §8.1's vocabulary rows: `drafted` until
  reviewed. A tier-2 label is a non-native reading of a page, which is a real limitation and the
  second reason tier 2 does not tune thresholds. **Trigger:** raising any tier-2 bucket to tier 1.
- **Images.** A rule that lives only in an image is out of the corpus, and typed-decisions §8.5's
  transcription path has the same trigger it always had: **the corpus finds a rule that lives only
  in an image**. It can only find one if a labeller sees the page and records it in `notes` — so the
  command prompts for it, and `notes` is where the trigger fires.
- **Any use as training data.** §2. **Trigger:** a written change to the Exa/Brave permission and
  TypeSafe's MCA §2.3, not a decision by whoever needs it.

## 12. Open questions

1. **Who labels tier 2, and against what.** Thirteen languages the labeller does not read. Machine
   translation to label from is a model scoring a model. The honest options are a native speaker per
   language, or accepting that tier 2 measures "does the pipeline do anything sane here" and never
   more — which is what §5.1 currently says it does.
2. **Whether the funnel gate's 20 programmes are the same programmes as the page layer's.** Sharing
   them is cheaper and makes the two layers consistent; not sharing them keeps the funnel from being
   scored on pages whose labels were written by looking at what the funnel found. Leaning towards:
   share the pages, but the funnel subset's `decoy_urls` are chosen before any run.
3. **How a corpus page that becomes unreachable is handled.** Dropping it shrinks a bucket below its
   floor silently; keeping it means scoring a fetcher against a page no fetcher can reach.
   `check_corpus` reports it; the rule is not decided.

## 13. Implementation

One plan, part 2 of this work, in this order:

1. `manage.py label_page`, the file schema, and the `id`/`text` agreement test — nothing else can
   start.
2. Tier 1 labelled to its floors (four languages), and gates 3, 8, 10, 11 turned on for those.
3. `manage.py check_corpus`, and the two plan changes of §9.2.
4. Tier 2 labelled to its floors, and §11.3's note-degradation confirmed to fire for any bucket
   below the bar.
5. `programmes.json` with its decoys, and the funnel gate on its named subset.

Gates 12 and 13 run after step 2 and are re-run after step 4, because a wording that wins in English
is not the wording that wins in Kazakh — which is the whole reason they are per-language.
