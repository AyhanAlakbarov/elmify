# Programme page reader: one read, verbatim statements, derived rules

Status: **design, ready for an implementation plan.** Date: 2026-09-12.

Replaces two readers of a programme's page with one, changes what the shared catalog stores from a
model's interpretation to the page's own sentences, and gives the long tail of programmes and
scholarships — the ones nothing in `catalog_seed.py` names — their own CV rules on top of STANDARD,
read from their own website, with no human in the loop.

## Why

Measured 2026-09-12 (`CLAUDE.md`, "The structure change has NOT been shown to improve extraction"):
`extract_program_profile` over the same FAU AI M.Sc. application page returned 13, 17 and 10
competencies on three calls; the structured input returned 18, 18 and 16. `record_program_profile`
deletes every `ProgramCompetency` row and writes whichever sample it got, so the shared catalog every
tenant reads is exactly as noisy as the noisiest single call, and `tailor_skills` reorders a
student's CV against it.

The variance is not the model's. Three design choices produce it:

1. **The catalog is keyed on the interpretation.** `ProgramCompetency.term` ("Mathematics") is the
   identity; `excerpt` — the page's words — is a side field. Dedup, replace and `exact_matches` run
   on the part that varies. The `WantedCompetency` docstring already says the excerpt "makes
   inventing a requirement cost a fabricated quote"; the design stopped one step short of making the
   quote the row.
2. **One sample defines shared state.** Replace-on-read assumes a stable read and there is none.
3. **Each question gets its own reader.** Competencies (`research/refresh.py`), the format enum
   (`documents/format_resolution.py`), and the CV-rules reader this work was about to add would be
   the third: three fetches, three prompts, three variances, three security reviews of one
   hostile-page hazard.

Neither existing reader has a production caller. `refresh_program_profile` and
`resolve_cv_format_requirement` run from tests only; the only writer of `cv_format_requirement`
today is `load_cv_format_requirements`, which loads the hand-verified CSV as `VERIFIED`. There is no
live behaviour to preserve, only tested contracts.

## Decisions

- **The sentence is the row.** The catalog stores what the page says, verbatim, and every reading
  of it is derived from stored sentences, never from a fresh model call over the page.
- **Every stored sentence is verified against the page.** A quote not found in the readable text of
  the archived snapshot is dropped. This is what makes stability near-deterministic: two reads are
  compared against the page, not against each other.
- **One reader per page, two derivations.** Skills for the SKILLS section (the other system) and
  CV rules for this one both come from the same read.
- **No human in the loop.** Owner's call, 2026-09-12: confirmation gates cause friction. The reader
  writes statements, rules and the format enum itself.
- **The one PII-routing decision has no model discretion in it.** `cv_format_requirement` selects
  `EUROPASS_API`, which sends a student's name, education and employment history to europa.eu. It is
  set from a FORMAT statement by a fixed keyword rule on the verified quote, never by the model's
  reading of it. No human, no discretion.
- **Derived CV rules are `ADVISORY_HIGH_RISK` and cite the sentence.** They never block a render;
  the counsellor sees the violation with the page's own words. STANDARD plus the page's rules on top.
- **Unchanged page, no model call.** The stored statements and rules are the cache, keyed to the
  snapshot. Invalidation is "the page changed" (`content_sha256`), not a timer.
- **Derivations re-run from stored statements without a refetch**, so a new constraint key or a
  fixed keyword rule reaches every programme already read.
- **Hand-verified rows are never overwritten.** A programme with `cv_format_verified_for_cycle` set
  keeps its `VERIFIED` format enum whatever the reader derives, exactly as today.

## Data model

### `ProgramStatement` (replaces `ProgramCompetency`)

Shared catalog, `apps/funding/models.py`. Same RLS shape as `ProgramCompetency`
(`0021_program_competency_rls.py`: `shared_catalog_select` for all, `catalog_ingestion_write` for
the `catalog_ingestion` role).

| field | type | notes |
|---|---|---|
| `id` | UUID | |
| `program` | FK `Program`, CASCADE, `related_name="statements"` | |
| `snapshot` | FK `OfficialSourceSnapshot`, PROTECT | the read this row came from |
| `kind` | `COMPETENCY` / `DOCUMENT` / `FORMAT` / `LANGUAGE` / `OTHER` | check constraint |
| `requirement` | `REQUIRED` / `DESIRED` | check constraint, as today |
| `text` | CharField(1000) | the verbatim sentence; **the identity** |
| `label` | CharField(200) | short model-given name, for display and `exact_matches`; never identity |

Unique on `(program, normalized text)` is enforced in the writer, not the database: the
normalization (casefold, whitespace collapsed) is code, and a DB constraint on raw text would let
"Mathematics." and "mathematics" coexist.

Migration: `RenameModel(ProgramCompetency → ProgramStatement)`, `RenameField(term → label)`,
`RenameField(excerpt → text)`, `AddField(kind, default="COMPETENCY")`, and **drop the existing
`UniqueConstraint` on `(program, term)`** — two different sentences may legitimately carry the same
label ("Mathematics" from the degree requirement and from the screening test), and identity is the
text now. Postgres keeps RLS policies
across `ALTER TABLE ... RENAME`, and `tests/tenancy/test_database_isolation.py::_SHARED_TABLES`
gains `funding_programstatement` in place of `funding_programcompetency`, which is what verifies
they survived. The check constraint on `kind` is added in the same migration.

### `Program.cv_constraints` (existing, gains its first writer)

Already a JSONField read by `constraints.rules_from_program`, already outranking every
`CatalogRule` scope in `resolve_rules`. The reader's derivation writes a list of `ConstraintRule`
dicts to it. Nothing else changes on `Program`; `cv_format_confidence=EXTRACTED` is reused to mean
"derived by the keyword rule from a verified statement".

Each derived rule carries: `rule_id` = `PAGE-<n>` (n = position in the read; `rule_id` is
`max_length=20`), `rule_text` = the statement verbatim, `source_url` = `snapshot.final_url`,
`enforcement` = `ADVISORY_HIGH_RISK`. `rules_from_program` validates each on read and raises on a
malformed one, as today — a derived rule that fails validation is a writer bug, never silently
skipped.

## The reader

`apps/research/reader.py`. Replaces the extraction half of `refresh.py`, all of `profile.py`, all
of `documents/format_resolution.py`, and `extraction.py::extract_program_profile` /
`ProgramProfile` / `WantedCompetency`.

```
read_program_page(*, program, source, store, parser, admissions_cycle,
                  retrieve=retrieve_official_source) -> ReadResult
```

Same guards as `refresh_program_profile`, unchanged: `source.source_type == PROGRAM` or
`UnprofilableSource`; `rate_limited("program-page", program.id, 4/hour)`; the `retrieve=` seam is
code-only (Decision B, `refresh.py` module docstring — carry that docstring over verbatim); fetch,
`require_same_origin` **before** `persist_snapshot`.

Then, in order:

1. **Unchanged page → return early, before `persist_snapshot`.** Compute
   `content_digest(fetched.body)` (the readable-content digest `persist_snapshot` would store as
   `content_sha256`); if it is non-blank and equals the `content_sha256` of the snapshot the
   programme's current statements point at, return `ReadResult(statements=<current>,
   model_called=False)`. No model call and no duplicate snapshot row — `persist_snapshot`'s
   `(source, sha256)` uniqueness would reject identical bytes anyway. This is the cache the owner
   asked for, and it is the largest stability lever in the design: a page that has not changed
   cannot produce a different read.
2. **One model call**: `extract_statements(parser, source_id=, page_text=readable_text(fetched))`.
   Developer prompt, in the style of the existing extractors (DATA labelled as data, never
   instructions): *quote every sentence or list item in DATA that states something an applicant
   must or should have, hold, submit, provide, or do; copy each verbatim; label its kind
   (COMPETENCY: a subject, method or body of knowledge; DOCUMENT: a document or its format, length,
   or content; FORMAT: the CV or résumé's required format or template; LANGUAGE: a language or test
   requirement; OTHER); label REQUIRED or DESIRED; give a label of at most six words.* Schema
   `Statements(statements: tuple[Statement, ...])`, `max_length=40`, `Statement(text ≤300, kind,
   requirement, label ≤200)`, `extra="forbid"`. `max_output_tokens` capped, `store=False`,
   `safety_identifier=privacy_safe_identifier(source_id)` — as today.
3. **Verify every quote.** `normalize(text) in normalize(page_text)`, where `normalize` casefolds
   and collapses whitespace. Drop what fails. Count drops; they are returned on `ReadResult` for
   the live check and logged as a WARNING with the count only.
4. **Dedup on normalized text.** Last occurrence wins, as `record_program_profile` does today.
5. **Replace, or keep.** Zero verified statements → return the current ones with
   `model_called=True, wrote=False` (a cookie wall, a login redirect and a refusal all look like
   this, exactly as today). Otherwise delete the programme's statements and write the new ones,
   in one transaction.
6. **Derive** (below), in the same transaction — only when step 5 wrote. Kept statements are
   unchanged statements, and re-deriving them would spend a model call to reproduce what is on file.

`ReadResult` is a frozen dataclass: `statements`, `dropped_quotes: int`, `model_called: bool`,
`wrote: bool`. The live check reads it; nothing else does.

## Derivations

`apps/research/derive.py`. Both functions take a `Program` and read `ProgramStatement` rows —
never the page, never the model over the page — so both can be re-run for every programme after a
rule change with no fetch and no read.

### `derive_cv_format(program) -> str | None`

Fixed keyword rule over `kind=FORMAT` statements, on normalized text. In order:

| the quote contains | sets |
|---|---|
| `europass` and any of `recommend`, `prefer`, `optional`, `may` | `europass_preferred` |
| `europass` | `europass_required` |
| nothing above | *(no change)* |

Written to `Program.cv_format_requirement` with `cv_format_confidence=EXTRACTED`, **unless**
`cv_format_verified_for_cycle` is set, in which case nothing is written. `funder_template` and
`structured_fields_only` are never derived: the first needs a template module that nothing derives
from a sentence (`_funder_dispatch` knows SISGP and RHODES by id), the second is a portal property
the page does not state. Both stay hand-curated in `SEED_FUNDERS`.

This is a keyword rule on purpose. It is the one derived value that routes a student's PII to a
third party, and the owner's no-human decision is honoured by removing the model's discretion from
it rather than by trusting that discretion.

### `derive_cv_constraints(program) -> tuple[ConstraintRule, ...]`

Over `kind in (FORMAT, DOCUMENT)` statements whose normalized text mentions the CV
(`cv`, `curriculum vitae`, `résumé`, `resume`, `lebenslauf`). One closed-schema model call per
programme, over the statements only:

*For each numbered statement below (DATA), say which CV constraint it states, if any. Allowed keys:
`max_pages`, `max_bytes`, `photo_allowed`, `date_of_birth_allowed`, `date_of_issue_required`,
`signature_required`, `language`. Give the value in the key's type. A statement that states no
constraint from that list is omitted. Never infer a value the statement does not give.*

Schema: `Derivations(rules: tuple[Derived, ...])`, `Derived(statement_index: int, key: <Literal of
the allowed keys>, value: int | bool | str)`, `extra="forbid"`. A `statement_index` not in the
input is dropped (the `judge_remainder` closed-list rule). The allowed keys are the subset of
`_CONSTRAINT_KEYS` a single page sentence can state; `required_fields`, `prohibited_content`,
`max_entries_per_section`, `no_unexplained_gaps`, `ai_use_policy` and `min_final_page_fill` stay
catalog-only because their values are structured judgements, not a number a sentence prints.

Each `Derived` becomes a `ConstraintRule` (provenance as above) and the list replaces
`Program.cv_constraints`. An empty derivation writes `[]` — unlike statements, an empty rule set
is a real result ("this page states no CV constraint"), and leaving stale rules from a previous read
would be the silent failure.

Because `ADVISORY_HIGH_RISK` never blocks, a wrong derivation costs a warning the counsellor sees
with the sentence attached — the price of no human gate, paid where it is cheapest.

### Skills

`documents/generation.py:137` filters `kind=COMPETENCY`. `tailoring.exact_matches` compares against
`label` (it compared against `term`; same field, renamed). `tailoring.judge_remainder` renders
`id | requirement | label | text` (it rendered `term | excerpt`). The rule pinned by
`test_no_programme_excerpt_ever_reaches_printed_content` — the page's words never reach a rendered
document — holds for `text` exactly as it did for `excerpt`. No other change: the judge is a
closed-list id matcher and does not care what the row's text is.

## What is removed

- `apps/documents/format_resolution.py` and its 14 tests. Its `FormatResolutionSource`,
  `_fail_closed`, the 0.7 threshold and the `document.format_unverified` audit event go with it —
  the reader has no "unverified" outcome to report, because a statement is either on the page or
  it is not written.
- `apps/research/profile.py` (`record_program_profile`), folded into the reader's write step.
- `apps/research/extraction.py::extract_program_profile`, `ProgramProfile`, `WantedCompetency`,
  `_PROFILE_MAX_OUTPUT_TOKENS`.
- The extraction half of `apps/research/refresh.py`. `readable_text` and its helpers stay and move
  to `reader.py` with their tests; `_ADMISSION_TERMS` widens to cover DOCUMENT/FORMAT vocabulary
  (`cv`, `curriculum vitae`, `résumé`, `document`, `upload`, `format`, `europass`, `pages`) because
  the reader now reads for those too — this is the "second extractor needs its own vocabulary" case
  `CLAUDE.md` names, resolved by there being one extractor.

## Security

Posture unchanged; surface reduced. One prompt over page content instead of two. The `retrieve=`
seam and `OfficialSource`-row-only signature carry over verbatim. Shared-catalog writes stay under
the `catalog_ingestion` role. Statement text is verbatim page text, so the injection surface is what
it was; the derivation prompt labels statements as DATA. `derive_cv_format` is deterministic — a
hostile page can make a programme Europass by printing the word, which it could already do by
printing the sentence; it cannot make the model do anything, because the model is not consulted.

## Out of scope

- **The production entry point.** Neither reader has one today and this change adds none.
  `read_program_page` is callable from tests and a manual probe, as `refresh_program_profile` is.
  Wiring it owes per-tenant rate limiting (`CLAUDE.md`, LLM/AI security) and the URL-restriction
  rule (only `OfficialSource` rows the catalog vouches for), and is its own change.
- **Voting across reads.** Verification against the page replaces it; if the live check below shows
  residual variance in *which* sentences are quoted, a union-of-N-reads step is the follow-up, not
  part of this.
- **Any change to the rendered CV.** Derived rules surface as advisory violations through the
  existing `render.py::_CHECKERS`; no new checker, no template change.

## Proof

Unit (no network, fake parser):

- a quote not in the page is dropped and counted; a quote that differs only in case or whitespace is
  kept; two statements normalizing to one text write one row
- zero verified statements keep the previous rows; a non-empty read replaces them
- same `content_sha256` → `model_called=False`, no delete, no write
- `derive_cv_format`: the keyword table above, both branches, and the `VERIFIED` short-circuit
- `derive_cv_constraints`: an out-of-range `statement_index` is dropped; an empty derivation writes
  `[]`; each written rule passes `rules_from_program`
- `resolve_rules` over a programme with derived constraints returns them ranked above every catalog
  scope, and `render_cv_with_warnings` reports them as `ADVISORY_HIGH_RISK` violations carrying the
  sentence — this is the end-to-end check that STANDARD-plus-page-rules actually reaches a render
- `_SHARED_TABLES` carries `funding_programstatement` and the RLS policies survive the rename

Live (`-m live`, before merge, the metric that matters):

- read the FAU AI M.Sc. application page three times with a real parser; assert the three
  normalized statement sets are **identical**, `dropped_quotes` is reported, and the derived
  `cv_constraints` are identical. This is the test the 2026-09-12 measurement failed.
- read it a fourth time from the same bytes; assert `model_called=False`.

## Next step

Write the implementation plan. Order: model + migration → `reader.py` (moving `readable_text`) →
`derive.py` → tailoring/generation rename → removals → live check.
