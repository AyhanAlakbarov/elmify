---
paths:
  - "apps/documents/**"
  - "tests/documents/**"
  - "docs/research/**"
---

## Who reads a CV warning — the student, not a counsellor

`render.render_cv_with_warnings` computes every advisory render warning and every `undecided` /
`unapplied` rule. But the preview and worker path goes through `render.render_cv`, which calls it,
raises `PreflightBlocked` on BINDING violations only, and drops every advisory one, so today no
screen shows them to anyone. The design rule stands: a rule nothing can act on is shown, never
dropped. Who it is shown to (the student, the assigned counsellor, or both; the owner decided
2026-10-13 that the counsellor sees everything) is an open owner decision.

## One ledger, every consumer

The platform is one synchronized system over the student's fact ledger (`VerifiedFact`). Every
consumer reads the same ledger: CV generation and rendering, the letter and storyline prompts,
skill tailoring, portal autofill (`portals.profile.verified_values`) and europa.eu
(`europass.europass_payload`). A category is never hidden from one consumer to protect it from
another; each consumer guards how it uses the fact instead. Example: the letter prompt may tell a
TIMELINE fact (an illness, a caring period) and may not add a diagnosis, cause, severity, person or
detail beyond the statement's own words. So a new category is wired to every consumer in the same
change, and any exclusion is an owner decision recorded here.

Exclusions (owner decision 2026-10-15, transcript plan 3b Task 7): a degree's checked transcript
courses (`courses` on its EDUCATION fact) reach the letter and story prompts now; the CV prompt and
Europass wait for the CV-quality design's coursework line; portal autofill never uses them (it takes
text values only). A course the student could not read (`courses_unconfirmed`) never reaches a
prompt. `verification.NOT_FOR_LETTERS` / `NOT_FOR_CV` hold the lists.

Europass carries a gap row in the captured work-experience shape (statement as occupation, empty
employer). `manage.py europass_canary` sends one and checks it is printed: verified live
2026-10-06. Rationale: owner decision 2026-10-06.

## The CV-requirement corpus — read this before measuring discovery or derivation

`docs/research/cv-corpus-programmes.csv` and `cv-corpus-rules.csv` are the hand-adjudicated
ground truth for "did we find the CV requirements this programme publishes"
(`docs/superpowers/specs/2026-09-15-cv-requirement-corpus-design.md`). Loader and scorer:
`apps/research/corpus.py`. The live runner `tests/research/test_cv_corpus.py` prints
recall/precision/localization per stratum and asserts hand-ratcheted floors; the headline is
**recall on BINDING requirements**, because a missed binding rule costs a student an
application and an invented one costs an edit they can decline. Rules of the file:
`seed_url` is the programme's front page, never a documents page (seeding with the rule page
defines discovery away); a `requirement_key` is always one the engine already has, with
`unapplied` for what the vocabulary cannot carry; hosts from `cv-format-eval.csv` and the
2026-09-15 survey may be `dev`, never `heldout` (`corpus.contaminated_hosts`). `manage.py
pool_cv_corpus --digest` fills source digests; `--pass vendor` pools candidate sentences into
`cv-corpus-candidates.csv` for adjudication. **That crawl is pinned to the seed's own domain**
(`tavily_crawl`, `allow_external: False`) — Tavily's documented default is `true`, and the first
vendor pass followed DAAD's "use the europass template" link and crawled
europass.cedefop.europa.eu, whose **single** page yielded 76 of that programme's 79 candidate
rows — its language picker, one row per `[dansk](…/da)` link. It read like a `CANDIDATE_TERMS`
problem (every one matched on the word "europass") and was a crawl-scope one; the 76 rows were
pruned by hand, since re-pooling spends credit for an answer the filter already gives. **One
page, so the crawl budget was not consumed off-site** — this is a precision fix and will not
recover the six programmes whose crawl returned nothing. Tavily is not measured as honouring
the flag, nor as counting a sibling subdomain (`static.daad.de`) internal to its seed. At 45
programmes the corpus demonstrates ≥95% and diagnoses losses; it cannot demonstrate 99%
(spec, "The measurement ceiling").

## The rule catalogs — read these before researching CV or letter conventions

`docs/research/` holds **216 already-researched rules**, each with a source URL, a
provenance tier, binding-vs-advisory, a confidence grade and a verified-for-cycle year,
cross-checked across two independent research runs:

- `cv-rules.csv` (93) — CV content rules
- `cv-style-rules.csv` (50) — CV style: layout, typography, elements, country norms,
  machine parsing. IDs are `S-0NN` and are cited by ID in code (`S-010`, `S-011`,
  `S-013`, `S-026`).
- `letter-rules.csv` (73) — motivation and reference letters
- `2026-09-14-letter-storytelling-evidence.md` (19 `N-` findings) — how the engine chooses
  and tells a letter's story per reader, and what it may invent (the why; anything a
  submitted document could check comes only from the ledger — owner's line, 2026-09-14, in
  the note's §4). Read it before researching narrative, "authentic voice" or
  AI-vs-human text again; the humanizer and detector questions are answered there too.

**Consult these before running a new research pass on how a CV should be written.**

Two traps the catalog itself records:

- **Only the funder rules (`R-*`) are seeded as `CatalogRules` and checked mechanically**
  (`apps/documents/catalog_seed.py`). Every `S-*` rule is prose in a CSV, enforced only
  where a human happened to cite it — so a new writer path inherits none of them by
  default.
- **S-032 vs S-008 is resolved — the table layouts stay.** Machine parsers do mangle
  multi-column and table layouts, and `cv_german_tabular.html`, `cv_europass.html` and
  `cv_funder_sisgp.html` are all real HTML tables. It binds nothing here, for two
  independent reasons: every source for the rule describes corporate job-application ATS,
  and a targeted search found no evidence either way about graduate-admissions portals;
  and the extension's portal upload (`extension/src/content/fill.ts::attachDocuments`)
  hands the PDF to admissions staff, not to a parser anyone has shown exists. **Owner
  decision 2026-10-14: table layouts stay, uploads included.** What would make it live: a
  portal shown to parse an uploaded CV. The answer then is a per-destination variant —
  `format_resolution.py` already picks one from what the programme requires — never a
  weakening of S-008.

## Repo and thesis readings reach letters through one function

`apps/documents/evidence/readings.py::usable_readings(student)` returns the student's checked
readings (CV evidence spec §11): summary, kind, names, dates, and bullets that each quote their
evidence verbatim and carry a Jev support verdict (`supported`, `rejected`, `unchecked`).
Whether a letter requires `supported` is the letter engine's choice. Nothing else may read
`EvidenceReading` — not generation, not the confirm list, not tailoring, not the portal
profile — and Part B (spec §10) is what places readings on a CV.
