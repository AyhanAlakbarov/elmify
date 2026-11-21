---
paths:
  - "apps/research/**"
  - "apps/documents/**"
  - "apps/funding/**"
  - "apps/ratelimit.py"
  - "tests/research/**"
  - "tests/documents/**"
  - "tests/funding/**"
  - "config/settings/**"
  - "apps/mailbox/**"
  - "apps/portals/**"
  - "ocr/read_pages.py"
---

**Model-calling modules today** (refresh with `git grep -l "\.parse(\|messages\.create(" -- apps`;
the per-module notes below cover only some of them, so the ordinal numbers they once carried are
dropped): `apps/documents/` — `dates`, `derive`, `evidence/extraction`, `fact_readers`, `evidence/signals`,
`generation`, `ingestion`, `letters`, `letter_verification`, `prompt_resolution`,
`research_fit/{anchors,classify,judge}`, `storyline`, `tailoring`; `apps/funding/explanations`;
`apps/mailbox/classify`; `apps/portals/learn`; `apps/research/` — `angles`, `batch_reading`,
`classify`, `extraction`, `funding_judge`, `locale_names`, `profile_cells`, `reader`, `tap_query`;
and through OpenRouter or Jev, `apps/research/{decisions,jev}`, `card_engine/readers` and
`engine_eval/chat`. Every one follows the reference pattern in the first bullet below.

## LLM/AI security

- `apps/research/extraction.py` and `apps/funding/explanations.py` are the reference pattern for any new LLM-calling code: untrusted content is explicitly labeled as data (not instructions) in the prompt, output is schema-constrained via Pydantic (`extra="forbid"`), and `max_output_tokens` is capped. Follow it, don't weaken it.
- Neither module is wired to a view or task yet. Before wiring one up, add per-tenant/per-user rate limiting in the same change — reuse `apps/ratelimit.py`'s `rate_limited()` (the fixed-window cache counter already used by the pack-command, MFA-verify, and student-message endpoints) rather than writing a new limiter, and an LLM-calling endpoint without one has no cost circuit-breaker. See the global `engineering.md`'s "LLM and AI-Feature Security Baseline" for the full rule.
- **The letter engine has a caller now: `manage.py draft_letter`** (`apps/documents/management/commands/draft_letter.py`). A console entry point, the same choice `ingest_evidence` made and for the same reason — §10 still gates the interaction surface, and a command opens none. It generates one letter for one student and one programme inside `tenant_scope`, reads **confirmed** facts only (`generatable_facts`), writes a `DocumentDraft` in `DRAFT`, and stops: `mark_letter_ready` takes an `accepted_by` because a person accepts a letter, and nothing in a command is a person. Two things it cannot work out for itself and says so rather than implying: without `--forbid` names the wrong-institution gate checks nothing, and `--render` writes to a path you name, never into the evidence bucket. The rate limit is inside `generate_letter` already (20/hour/student, two model calls per generation plus up to six for the written-requirement check).

- `apps/documents/evidence/extraction.py` follows the same reference pattern. Its one call,
  `read_repo`, is reached only through `apps/documents/evidence/refresh.py::refresh_evidence` —
  the document worker's `refresh_evidence` job (queued when a GitHub username is set or a CV or
  "Thesis or report" upload is promoted) and `manage.py ingest_evidence --student`. Every model
  read, the one retry included, counts against `rate_limited("evidence_intake", ...)` (20/hour
  per student), and reaching it stops the refresh quietly rather than raising into the worker.
  The login never reaches a prompt: the evidence text carries no repo owner and scrubs the
  login. Who wrote a commit is not checked (owner, 2026-10-14: trust the student), so there is no
  owner check any more; what protects a CV is `evidence/checks.py` — every bullet quotes its
  evidence verbatim and carries only numbers its own spans state, and Jev
  (`decisions.ask(record=False)`, decision `evidence_support`, sent to TypeSafe's Jev through
  OpenRouter — `DECISIONS_BASE_URL` — 60/hour per student, always on since the TypeSafe DPA
  was accepted 2026-10-15) gives each a supported / rejected / unchecked verdict. The OpenRouter
  hop, thesis text included, was accepted by the owner the same day.
  Readings live in `EvidenceReading`, read only by `evidence/facts.py`; the skills a reading
  suggests are unconfirmed SKILL facts. Live checks:
  `tests/documents/evidence/test_live_contracts.py` and `tests/documents/test_live_evidence.py`,
  excluded by `addopts`; run them with `-m live`.
- **`generate_cv(programme=...)` costs a second model call.** `apps/documents/tailoring.py::tailor_skills` is wired into generation and runs only when a programme is passed and that programme has `ProgramStatement` rows; it carries its own per-student limiter (`skill-match`, 20/hour) on top of generation's own (10/hour). It may only ever reorder and drop skills — never add one, and never copy a statement's text into the document, which is the programme's own wording appearing as the applicant's claim.
- `apps/research/reader.py::extract_statements` and
  `apps/documents/derive.py::derive_page_rules` call models. Both are reached only
  through `apps/documents/program_rules.py::read_and_derive`, which has no production
  caller: the chain runs from tests and the live check only, so no request path reaches
  either model today. Four constraints bind whoever wires it:
  - the per-tenant rate limiting the rule above requires (`read_program_page`'s existing
    `rate_limited` call is a per-programme cost circuit-breaker, not the per-tenant/per-user
    limiting a view or task needs);
  - only ever profiling `OfficialSource` rows the catalog vouches for, below;
  - `read_and_derive` holds one database transaction open across the HTTP fetch, three statement
    reads and either the grammar requests or up to six judge calls. Correct for consistency -- it is what makes a programme's statements
    and its derived rules roll back together -- and expensive at catalog-ingestion scale:
    idle-in-transaction for tens of seconds per programme. Wiring this up means deciding
    whether that cost is acceptable at the expected call volume, not assuming the current
    shape scales unchanged. **Since 2026-09-26 that transaction also spans the back-to-back
    grammar requests (slots, values, page facts) and holds uncommitted `DecisionRecord`
    inserts**, so two workers reading the same shared page both pay for the same answers and
    the later insert waits on the earlier row's unique-key lock; the structural fix --
    decision writes on their own autocommit connection -- is plan 2's. And
    `read_and_derive(budget=None)` applies no run budget or monthly ceiling, so whoever
    wires a production caller must pass `decisions.run_budget()`;
  - `manage.py rederive_rules` re-asks stored sentences without a refetch. It bypasses
    `read_program_page`, the only place `rate_limited` is called, and carries its own budget;
    a change to it must keep one.
- **`apps/documents/research_fit/` calls models** (topic phrase, classifier,
  three-reading judge) and the first caller of a search provider from a per-student path. Its
  query never carries the student — `anchors.guard_phrase`, pinned by
  `tests/documents/research_fit/test_service.py::test_no_query_ever_carries_the_student` — because
  Exa ToS §1.2(c) and Tavily §9.2 license query text (`docs/legal/2026-09-provider-terms.md`). It
  has its own `research-fit` limiter (20/hour per student) and a per-tenant daily billed-cost
  ceiling (`RESEARCH_FIT_DAILY_CEILING_USD`) — **but that ceiling meters SEARCH spend only**. The brake is a cap
  rather than a price, because a dollar figure needs a per-model price table that goes stale in
  silence: `service.MAX_PAGES_CLASSIFIED` (6) bounds the pages one proposal classifies and judges,
  checked at every level of the search, giving `MAX_MODEL_CALLS` = 28; the calls made are counted
  onto `ResearchFitOutcome.model_calls` and logged with every outcome. Raising the cap re-opens the
  tail. **The fetch half is bounded separately and must stay that way** (design D15): every page
  read is a billable vendor credit, and `MAX_PAGES_CLASSIFIED` cannot bound it because it counts
  pages successfully READ — a run whose fetches all fail walks the whole search space paying for
  every attempt. So one `SweepBudget` per proposal (`RESEARCH_FIT_FETCH_CREDITS`) travels down
  through `pages.fetch_page`, and `FetchBudgetExhausted` is the one exception that function lets
  out, because it is a signal to stop the whole search rather than a fact about one page. Its
  dollars are added to `spend_within_ceiling` as they are charged, so the per-tenant daily ceiling
  finally sees a proposal's whole cost rather than its search half. Sentences are split by code and models only classify
  them, so no model ever authors a name the letter cites. Research-fit classifies through
  `research_fit.classify.FrontierClassifier` only; any other Jev use goes through the
  typed-decision client, `apps/research/decisions.py`, except the provenance vetoes'
  `apps/research/jev.py` (2026-09-27: the unwired second Jev client at
  `research_fit/jev.py` was deleted -- a duplicate, never a default, that the "no student text to
  Jev before the DPA" condition was written only against). Design:
  `docs/superpowers/specs/2026-09-22-letter-research-fit-from-the-student-design.md`.
- `apps/research/funding_judge.py` calls models, reached only from
  `run_discovery(funding_parser=..., funding_claude=...)`, i.e. `manage.py discover --funding`, which
  refuses to start without `ANTHROPIC_API_KEY`. Every line of a page's funding sections gets a closed
  verdict from three readings -- two `OPENAI_EXTRACTION_MODEL` phrasings and one `ANTHROPIC_JUDGE_MODEL`
  -- and a row is served only when all three agree on every deciding label of every line of the award
  (`docs/superpowers/specs/2026-09-14-funding-reader-precision-design.md`). Everything short of that
  waits in `manage.py funding_review` for a platform operator; a decision there is bound to the page
  version (`reviewed_sha256`) and every tenant sees it, so it is never a tenant action.
  **`FundingOpportunity.served` is the only flag a student-facing path may read**; `funding/pool.py`
  and `research/spine.py` read it for the student pack, PROGRAM/HOLDER scope only. Still true: an award withdrawn from a page keeps its `served` flag until that page
  is re-read, and it reads only `one_programme_per_site` catalogue leads (`pipeline._fund_page`) until
  an INSTITUTION-scope row's origin is checked against `institution.official_website`. Anthropic's
  Usage Policy lists admissions as high-risk and wants human review before dissemination; served rows
  have no human; the owner's 2026-10-08 position (platform-level AI disclosure, below) covers it.
  Measured live 2026-09-16 on 497 real EACEA leads,
  `docs/superpowers/2026-09-16-funding-reader-precision-run.md` — read it before assuming what
  `served` actually captures; a 2026-09-22 follow-up in the same file separates reading-quality gaps
  from a schema gap (temporal/administrative phrasing) from a verbosity penalty in the per-line
  grouping rule.
- `apps/research/angles.py` calls a model: one schema-constrained call per
  (country, family, language), following the reference pattern (the request labelled DATA,
  Pydantic output `extra="forbid"`, `max_output_tokens` 3,000, `store=False`) and its own
  `sweep-angles` limiter (`SWEEP_ANGLE_GENERATIONS_PER_DAY` per (country, family)). Its only
  caller is `manage.py generate_sweep_angles`, operator-run, which refuses to generate until a
  per-language kind-word vocabulary adapter exists — kind words are never translated by the
  model — and `--from-steering` writes one hand-written angle as the interim. Its input carries
  no student field.
- **`apps/documents/fact_readers.py` reads a student's diploma or language certificate** (spec
  `docs/superpowers/specs/2026-10-12-document-fact-reading-design.md` §5.3). Two readers from
  different vendors (`FACT_READING_READERS`, through OpenRouter; empty means off) quote fields into a
  closed per-kind schema (`extra="forbid"`, `FACT_READING_READER_MAX_TOKENS`, one retry, text labelled
  untrusted data). Code proves every quote against the page Azure read **as pictures**
  (`ocr.flatten`), so a model can point at a value but never author one. Never used for a passport:
  no language model reads a passport, and `generatable_facts` drops ID_DOCUMENT rows, so never add
  one to a prompt.
  - **The rendered image is the hidden-text boundary.** `ocr/read_pages.py::flatten` removes text
    below the size floor (glyph height = font size x hypot(c, d)) and invisible render modes before
    rendering, never by colour (white-on-dark is real text), pre-checks every image's declared size
    including `/SMask`, and refuses `page_too_large` rather than shrinking. `visible_text` is a
    cross-check only. Form XObject and annotation text is an accepted residual: the uploader is the
    student, and proven never means genuine.
  - **The transcript reader does not use that boundary yet.** `read_pages.py::_pdf` takes a page's
    text layer without `visible_text`, so a scanner app's invisible OCR layer reads as "exact" and
    hidden text reaches the transcript readers. Closing it is the transcript reader's change.
  - The readers' copy has names, date of birth and ID numbers replaced
    (`text_reading.strip_identifiers`); stored facts never are. The module does no limiting itself:
    its caller (`document_reading`) checks `rate_limited("fact-reading", student)` hourly and
    `rate_limited("fact-reading-readers", tenant)` daily before any call.
  - **A value is proven only when** both readers quote the same value, every occurrence on the page
    reads confidently, a score holds exactly one number, a born-digital PDF shows it in its visible
    text, and it passes the per-test ranges. An ambiguous numeric date is never proven.
  - **A read value never replaces what its row holds** (`fact_writer._attach`). A degree and a
    sitting are one row each; a differing value waits on the `DocumentReading` for the student to
    adopt (`adopt_document_value`) or keep. `correct_fact` supersedes an EDUCATION or LANGUAGE row
    with the merged payload, never a one-key row beside it (that would count as a second degree). A
    diploma matching no confirmed degree is asked as "Is this a new degree?" unless the student has
    none, and `placed_whole_rows` keeps a merged diploma's hidden row from being confirmed.
  - **A date the code cannot normalise is never written by a tap** (`fact_writer.needs_typing`);
    the student types it. The latest sitting is ordered by ISO `test_date` only.
- **Funding readings are bought three ways (`model_cost.ReadingTier`): standard, OpenAI flex, or
  both vendors' batch APIs (`batch_reading.py`).** The prompts and the decision are the synchronous
  path's byte for byte (`funding_judge.reading_prompts`, `decide`); only the transport differs, and
  `test_batch_reading` pins that a batched read decides what a synchronous one does. Two rules:
  a request a batch did not finish is *missing*, and a page with a missing reading writes nothing —
  never ABSTAINED rows, which would let `withdraw_unread` unserve awards the page still states; and
  nothing may hold a transaction across `read_funding_batched`, which can wait 24 hours per batch
  — up to 48 when a tie-break batch follows. **A programme page a batch did not finish is not read
  again by the next run unless its text changed**: `run_discovery`'s unchanged-page short-circuit
  checks claims, not `funding_read_at`, so it stays PENDING in `funding_recall`. The sync path has
  the same gap when the budget cuts a read short; batch mode makes it the ordinary failure. Known,
  not fixed (it changes the short-circuit, not a cost). A flex 400
  raises `ReadingTierRefused` instead of becoming a lost reading, because a lost reading on every page
  reads as a catalog that states no funding. Every reading's tokens are recorded (`CostMeter`, and
  `OfficialSourceSnapshot.funding_read_cost` per page read) and priced from
  `MODEL_PRICES_USD_PER_MTOK`; a model with no row is *unpriced*, never zero. An answer that came
  back off-schema was still billed, so it is never counted `lost` (a call that raised, whether it
  was billed unknown): synchronously its usage is gone with the SDK's rejected parse, so it counts
  `unmetered` (billed, usage unknown); in a batch its body still carries `usage`, so it is priced.
- **`ProgramStatement` is shared-catalog data with third-party content in it.** Every tenant
  reads that table (`tests/tenancy/test_database_isolation.py::_SHARED_TABLES`), and its `text`
  and `label` come from a web page a model quoted. So whoever wires the writer decides
  *which URLs may be profiled*, and that decision is a cross-tenant one: if a tenant can steer
  the URL, a hostile page becomes content every other tenant reads. Profile only URLs already
  reachable from an `OfficialSource` the catalog vouches for — never a URL supplied per-request.
  Writes are RLS-restricted to the `runtime_engine` role, which limits who can write but not
  what the page said. Its rows are verbatim sentences verified against the archived page, never
  a model's paraphrase — `reader.verified_statements` drops anything not on the page, which is
  what makes a re-read stable.
- **Decision B vouches for the SOURCE ROW, not the BYTES — `reader.py` now enforces that.**
  `read_program_page` reaches a page through `retrieve_official_source` → `fetch_page`
  (Firecrawl, then scrape.do on failure — `.claude/rules/web-fetching.md`), and each vendor's final URL runs
  through `validate_public_url`, which rejects *private* addresses but does not require the vendor
  to have stayed on one origin — a public attacker-controlled host is followed happily. Without a
  further check, an off-site redirect from a compromised official URL becomes shared-catalog rows
  every tenant reads. `read_program_page` therefore calls `require_same_origin`, which compares
  the ORIGIN (scheme
  + host) of `fetched.final_url` against `source.canonical_url` and raises `OffSiteRedirect`
  **before** `persist_snapshot`, so off-site bytes reach neither the model nor the evidence
  bucket. `final_url` itself comes from whichever vendor answered: Firecrawl's own re-validated
  `data.metadata.url`, or, for scrape.do, its `scrape.do-resolved-url` header
  (`.claude/rules/web-fetching.md`; absent is a failure).
  **Origin, not the whole URL, and do not "tighten" it to one.** Official pages redirect `/x/`
  to `/x` and `/x` to `/x/2027-intake` as ordinary housekeeping; whole-URL equality rejects the
  real FAU programme page over a trailing slash. Scheme is part of the comparison because
  `validate_public_url` permits http, so an https source could otherwise be walked down to http
  on its own host. A source that genuinely moved hosts is a catalog fix — update
  `canonical_url` — which is a human decision, recorded, and that is the point.
- **Never hand a programme page's raw HTML to a model; use `reader.py::readable_text`.**
  `extract_statements` caps its input at 24,000 characters and a modern university page
  spends its first 24,000 on `<head>` and inlined CSS — FAU's AI M.Sc. page is 422,515
  characters in which "admission" first appears at 163,315. The model reads a stylesheet, finds
  no statements, and `read_program_page` treats a read that verifies no quotes the same as one
  that returned none — it keeps the previous rows standing — so the whole path fails
  **silently**: a page that reads as saying nothing is indistinguishable from one that says
  nothing. `readable_text` strips chrome (`<main>` rule below) (that page: 422,515 -> 10,408
  characters, all prose). Measured, not inferred.
- **`readable_text` emits structure, not a run of prose, and that is load-bearing.** Headings
  keep a `#` marker, list items a `- `, table rows their pipes. `text_content()` did not: it
  turned a document checklist into flat prose in which "no longer than two pages" no longer
  belonged to any particular document. The association lived in the markup, so flattening
  destroys information no prompt can recover — do not "simplify" the markers away. Measured on
  TUM's Informatics M.Sc. page (416,585 raw): the new output carries `Credits` / `- 120 ECTS`
  and `Admission Category` / `- Aptitude Assessment for Master` as label-and-value; the old one
  ran them together.
- **HTML comments are stripped explicitly, and with `strip_elements(..., with_tail=False)`.**
  `text_content()` dropped them for free because XPath `string()` does; the block walk recurses
  into anything that is not a leaf block, so the filter had to become deliberate — otherwise
  invisible page text reaches the model and a keyword in a comment can keep a section the
  visible prose never mentioned. Use `strip_elements`, never `getparent().remove()`: a comment
  sits inside a sentence, and `remove()` takes its tail with it (measured — "A degree<!-- note
  --> is required." lost " is required.").
- **One read is now three, unioned (`reader.py::_READS = 3`).** Each call to
  `read_program_page` asks the model three times against the same archived page and pours
  every response into one `verified_statements` pass, so the stored set is the union of the
  three. A union member is verified against the page exactly like any other quote, so it can
  only ever be a true sentence the other two calls missed — union was chosen over a quorum
  for that reason: a 2-of-3 rule discards precisely the sentence one read found, which is the
  observed failure (DAAD PRIME derived `europass_preferred` on one run and `any` on the next,
  same page, same code). **The cost lands only on a page whose text changed** — the
  `content_sha256` cache returns before any model call — so the ceiling is `_READ_LIMIT` ×
  `_READS` = 12 model calls per programme per hour. Two consequences worth knowing before
  changing anything here: `dropped_quotes` is now a sum over the three calls, so an
  unverifiable quote counts three times; and when two calls label the same sentence
  differently, dedup's existing last-occurrence-wins settles it arbitrarily. That last point
  is left arbitrary on purpose — demoting a sentence from FORMAT to DOCUMENT hides it from
  the format derivation (`derive_page_rules`), so the cost is a missed mandate, never a student's PII sent to europa.eu
  on a misread.
- **Verification removes fabrication; it does not remove selection variance.** The model is not inventing text it quotes — it is choosing a
  different subset of genuinely-on-the-page sentences on almost every read, and nothing in
  `verified_statements` constrains which true sentences get selected, only whether a
  selected one is true.
- **Union narrows the variance and does not remove it.** Do not re-derive this;
  do not report the union as having settled stability.
- **The live check now asserts the DERIVED RULES, not the statement set**
  (`tests/research/test_reader.py`'s live `test_three_live_reads_of_a_real_page_derive_the_same_rules`).
  `cv_constraints` is compared on `(key, value)`, never verbatim: `rule_id` carries the
  sentence's index on the page, so two reads quoting a different number of earlier sentences
  write different ids for the same rule. The statement-set spread is still printed every run,
  so a collapse in coverage stays visible. **The check needs a second page, one that actually derives a
  value, before the union can be called settled.** The natural candidate is whichever page
  produced the DAAD PRIME flip; its URL is not recorded in this repo, which is the first thing
  to fix. A page whose derivation is empty can only ever prove the absence of a regression.
  Measurement rounds: `docs/superpowers/specs/2026-09-12-program-page-reader-design.md`.
- **`<main>` is used only when `<main>` really is the page** (`_body_lines`, `_MAIN_SHARE`).
  It was always a proxy for "the relevant part" and section selection replaced it as the mechanism,
  so where the proxy is wrong it is now dropped. Measured: `<main>` holds 99.7% of SISGP's prose,
  87% of Sciences Po's, 80% of Rhodes', 63% of JASSO's — and 15% of Türkiye Bursları', whose
  headings and body copy all sit in siblings, so preferring it discarded 85% of the page. A shell
  `<main>` is not a page that says nothing, and the two were indistinguishable before this. The 0.6
  threshold rests on that ONE calibrating case and the fact that the change leaves the other five
  pages byte-identical; re-derive it if a page lands between 15% and 63%.
- **Only the sections mentioning admission are kept** (`_ADMISSION_TERMS`, `_selected`), and a
  page matching nothing degrades to the whole page rather than to silence — silence is the
  failure mode that hides, for the same reason as above: a read that verifies nothing keeps
  the previous rows rather than emptying the catalog. That vocabulary is
  what this caller reads FOR; a second extractor reading for something else (CV-format rules,
  say) needs its own, never a widening of this one. Widened until it matches everything, it is
  the same as not selecting at all.
  **Since 2026-09-18 it runs only on a page that would not fit `_MAX_PAGE_TEXT_CHARS`, and it
  logs what it dropped.** The cap is the only reason to select; on a page that fits, an English
  vocabulary can only lose. Measured over ten real programme and funder pages (AMIR, MEMBIOMED,
  i-MESC, MathMods, WE-TEAM, EuroPubHealth, EMJM-Imaging, SISGP, Eiffel/Paris-Saclay, FAU):
  **selection keeps 95–100% of the prose on every one, and nine of the ten are under the cap** —
  so it was removing a couple of percent while carrying the whole risk that a section it cannot
  read (a CV requirement in Turkish, Russian or Kazakh) is dropped before any model sees it,
  silently, on a page whose one incidentally-matching section stops the no-match fallback firing.
  **A share floor is the unsound alternative — do not re-propose it:** the case where selection is
  most right (mostly campus life, one admission section) and the case where it is most wrong (a
  page in a language the vocabulary misses) both keep a tiny share, so share cannot tell them
  apart. Fitting the cap can. The 95–100% figure also says the filter earns very little; deleting
  it is a live question, and an owner decision rather than a cleanup.
- **A PDF is read as a PDF** (`apps/research/pdf.py::pdf_text`), not decoded as UTF-8. egress allows
  `application/pdf` and a funder's checklist is often one; the old branch handed the model mojibake.
  The pypdf call, its wider error set (`PyPdfError` **plus** `AttributeError`/`ValueError` out of
  pypdf's own recovery code — measured on 300 corrupted PDFs) and the kerning repair moved out of
  `documents/ingestion.py` into `research/` because the import direction is documents → research;
  ingestion now wraps it and still raises `UnsupportedUpload`. A PDF with no text layer, or one pypdf
  refuses, is `UNPARSEABLE` — never a document that states nothing. And **`harvest.change_digest` is
  the one rule for "did this source change?"**, used by `persist_snapshot` and `read_program_page`
  alike: while only one of them knew about PDFs, a PDF source never cache-hit and every run re-read
  and re-paid for it.
- **Overflow is logged, not swallowed.** `page_text[:24_000]` cut mid-word and told nobody.
  `_capped` cuts between blocks and emits a WARNING naming how many lines were dropped, because
  a page we only partly read must not look like a page that said nothing.
- **A merged rule carries the strongest enforcement of the rules it came from.** Since
  2026-10-14 `resolve_rules` is the CV half of the requirement list
  (`apps/documents/requirement_list.py`, spec 2026-10-12 §6.4): theirs (programme page,
  FUNDER, INSTITUTION) beat ours (UNIVERSAL, TRACK, COUNTRY) even when theirs is soft;
  between theirs the stricter value wins per key; and the merged rule keeps the strongest
  enforcement of every contributor, losers included. **This is a PII boundary, not tidiness**:
  `render.py::_blocked_by_content_only_rules` inspects BINDING rules only, and every seeded
  BINDING rule is FUNDER, where "required beats not stated" keeps a page sentence from
  removing a funder's requirement. A page CAN now beat one of OUR BINDING rules on value
  (theirs beat ours); it keeps the BINDING enforcement. Before any europa.eu payload,
  `render.without_banned_content` strips the photo, date of birth and hyperlinks a ban names,
  whatever its enforcement, so a soft rule cannot let data out. Pinned by
  `tests/documents/test_catalog_rules.py` (`test_a_derived_rule_cannot_unlock_the_europass_pii_egress`,
  `test_an_advisory_programme_rule_cannot_displace_a_binding_one`,
  `test_no_seed_rule_of_ours_is_binding_on_a_content_only_key`,
  `test_a_page_rule_cannot_relax_a_binding_funder_date_of_issue_and_unlock_europass`),
  `tests/documents/test_requirement_list.py::test_no_content_only_key_merges_as_information_or_first_seen`
  and `tests/documents/test_render.py::test_a_soft_page_ban_cannot_let_personal_data_reach_europa_eu`.
- **Since 2026-09-26 a page is read by the typed grammar, and the three-reading judge below is the
  fallback.** With a decision provider configured (`OPENROUTER_API_KEY`, Jev through OpenRouter),
  `derive_page_rules` asks two typed requests per page plus one page-level request, over four
  slots and closed lists, and projects the answers onto sinks that already exist
  (`rule_sinks.py`). The bar is 0.85, with three phrasings on the Europass format. An uncertain
  reading becomes a note on the document; no person is waiting on it. With no key at all, the
  judge described below runs unchanged, so a missing key degrades cost, not correctness. An
  outage is not a missing key: it raises and the page's previous rows stand
  (`DecisionsUnavailable.kind`, `not_configured` vs `failed`, tells the two apart). The judge is deleted only when the page-corpus
  gates of the 2026-09-26 addendum §8 pass on Jev. Its measurements stay the record: the keyword
  rule's 61%, the Swiss supervisor's-CV attribution error, and the rule that a programme rule may
  not lower a key's enforcement. Design:
  `docs/superpowers/specs/2026-09-22-typed-decisions-and-multilingual-sources-design.md` §6, as
  amended by `2026-09-26-requirement-reader-addendum-design.md`.
- **The grammar is closed on purpose, and `unapplied` is a feature.** A page can state a
  requirement no operation carries, such as the first "publications in APA style". The sentence is
  kept, shown on the document and counted. It is never passed to the writing model as a free
  instruction: that is the door a hostile page would use to reach the generator, and the way the
  old attribution errors got in. When the count shows a kind is real, add the operation and its
  handler in code, then run `manage.py rederive_rules`. Every programme that ever stated the rule
  gets it without a page being refetched.
- **The CV-format decision is three readings, from two model families, agreeing on the ACTION, and
  nothing else — the keyword rule is gone.** Design and measurement:
  `docs/superpowers/specs/2026-09-13-format-decision-guarantee-design.md`. Measured on 48 real and
  synthetic sentences (`docs/research/cv-format-eval.csv`, pinned by a `live` gate in
  `tests/documents/test_derive.py`): the keyword rule scored 61% and was wrong in the PII direction
  on phrasing it did not know ("we suggest", "advisable", "Wir empfehlen" → `europass_required`); a
  local NLI classifier 54%; `OPENAI_EXTRACTION_MODEL` 100% unanimous on the renderer choice. So:
  `derive.py::candidates` finds the sentences by code over the WHOLE page (every `europass` line,
  every CV-term line ∪ the statement read's DOCUMENT/FORMAT sentences — the vocabulary does not
  know özgeçmiş); `_judge` asks one closed question `_SAMPLES` times in three phrasings;
  `decide` writes the format action, a constraint or a directive only where EVERY surviving sample
  agreed — an advisory
  rule that is wrong costs a warning the student reads beside the quote, one that abstains costs
  the criterion never reaching the CV, while a wrong action ships the student's data to europa.eu.
  Anything short of its bar writes `any` + `UNDECIDED` + an `undecided` rule carrying the sentence,
  which `render_cv_with_warnings` puts in front of the student. Negation, softening and a stated
  choice are all things the closed question answers, each pinned in the gate by the real sentence
  that motivated the old guard. **A sentence naming a referee, supervisor, host or employer is the
  one that it does not answer**: it never yields a rule or a directive, and `derive._THIRD_PARTY`
  enforces that in code — measured live 2026-09-14, two of three readings attributed "Short CV (max.
  2 pages) from this academic supervisor." to the applicant. The guard marks the OUTCOME
  `undecided`/`third_party`; it never drops the sentence, because a skipped sentence is silent.
  **Two voices since 2026-09-18: the regex, and a required `about_whom` field on every directive
  verdict** (`applicant | third_party | unclear`, no default — a skipped answer must not read as
  "the applicant's"). Either one withholds the line, `unclear` included. Ten English words cannot
  read a German or Kazakh page; the schema field can, measured 21 of 21 right across four
  languages on 2026-09-18, at no cost in abstention on the 48-row gate.
  **Since 2026-09-14 the third reading is `ANTHROPIC_JUDGE_MODEL` (`config/settings/base.py`)**, owner decision,
  because three samples of one model share its systematic bias. So a Europass action needs both
  families to agree while Claude's reading survives. Two limits stay: a refused, truncated or
  off-schema reading from either family is dropped and the page is decided by the two survivors,
  as two survivors always were (logged either way; a lost Claude reading logs "judged by one model
  family"), and a reading is dropped only after its one retry also fails; and a *unanimous wrong*
  answer still never abstains. Advisory rules need unanimity (owner decision, 2026-09-14). Under unanimity one thin reading abstains the whole page, **so each reading
  is now asked once more when it comes back missing (refused, cut off, off-schema) or thin (skips any
  line)** — `derive._with_one_retry`, never a loop. **Cost:** at most six judge calls per changed
  page, not three, and only on a failure. Both SDKs raise `ValidationError` inside `parse()` on an off-schema answer; the OpenAI
  readings did not catch it and one crashed a whole round — now one dropped vote. Round-by-round
  measurements: `docs/superpowers/specs/2026-09-13-format-decision-guarantee-design.md`. Wiring a caller
  owes `ANTHROPIC_API_KEY` (the worker task definition does not carry it) as well as the rate limit. **Anthropic's Usage
  Policy lists "Academic testing, accreditation and admissions" as high-risk**, requiring qualified
  human review before dissemination and AI disclosure where outputs reach individuals. The owner chose
  Sonnet 5 with that clause in front of them. **Owner position, 2026-10-08:** the clause is met by platform-level AI disclosure (students are
  told once that the platform uses AI) plus robustness (verified-only, certified readers); no human
  review is added before serving and no per-result AI label is shown. Do not re-raise it as a blocker.
- **A reader block is not a sentence, and two things assume it is.** Measured 2026-09-18 on
  MEMBIOMED's real how-to-apply page: `candidates()` returned two, and the longer was **1,935
  characters** — a whole document checklist in one `<p>`. (1) Both quote stores cap at
  `constraints.QUOTE_MAX_CHARS` (1,000), so the page raised `ValidationError` out of
  `derive_page_rules` and, because `read_and_derive` holds one transaction, took the statement
  write with it — and `PageDirective` is re-validated on *read*, so such a row would have broken
  `generation.py` and `gaps.py` too. `derive._quote` now clips with a `[...]` marker instead:
  splitting blocks into sentences would change what the judge is asked about on every page, which
  is a measured surface, and needs a splitter for every language the catalog reads. (2) The same
  block contains "Reference letters", so `_THIRD_PARTY` matches the whole paragraph and withholds
  the applicant's own rule with it — right about the block, wrong about the sentence. That one is
  **open**; it is the real argument for sentence splitting, to be measured against the 48-row gate.
  Recovery measurement and the full table: `docs/superpowers/research/2026-09-18-cv-rule-recovery-given-the-page.md`.
- **`Program.cv_directives` is the third thing a page can set, and it is typed.** `include(<field>)`,
  `order(<section>, chronological|reverse_chronological)`, `emphasise(<section>)` over the closed
  lists `derive._INCLUDE_TARGETS`/`_SECTIONS`, pinned to `CVContent` by test. `include` reaches the
  generation prompt as a field name (never the page's sentence) and, when the ledger lacks the
  field, becomes a `PROGRAMME_REQUIRED` gap question (`gaps.programme_required`) with the sentence as
  evidence; `order` and `emphasise` are applied at render (`render.apply_directives`,
  `_section_order(emphasise=)`). **There is no `exclude`**: the one directive a hostile page would
  want is the one that hides a field. A sentence all three readings agree states a CV requirement
  no field, section or key can carry is written as an `unapplied` rule — shown, never dropped.
  `constraints._MULTI_KEYS` keeps every `undecided`/`unapplied` rule through `resolve_rules`, which
  otherwise merges by key.
- **A page under 1,500 readable characters at 20,000+ bytes is `Readability.SHELL` on the snapshot
  (floor: `egress._MIN_READABLE_CHARS`), and
  derives nothing.** Measured shells: 289 / 265 / ~1,000 characters at 52,998–458,728 bytes; the
  smallest page that read fine is 3,095. Two-sided because a 300-byte page whose text is the page
  is not a shell. Previous rows stand; a human confirms whether it is a shell or a genuinely short page.

### A requirement the reader can see and the engine cannot act on

The format derivation (`derive_page_rules`) never derives `funder_template` or `structured_fields_only`, and that is correct:
the first needs a template module (`render.py::_funder_dispatch` knows only SISGP and RHODES), so
deriving it from a sentence would route every other funder to `UnsupportedRenderVariant`.

The consequence is measured, 2026-09-12, against the Swedish Institute's real SISGP page. The reader
stored "You must use SI's provided template for CV 2026/2027." as a REQUIRED FORMAT statement — it
read the requirement correctly — and `cv_format_requirement` stayed `any`. For SISGP that is
harmless, because `SEED_FUNDERS` carries `funder_template` by hand. For a funder nobody has
curated, the CV renders STANDARD, the student sees no warning, and the page's own "use our
template" sits in `ProgramStatement` with nothing reading it.

Closed 2026-09-13: a FORMAT sentence naming a template the engine does not know is the
`other_template` verdict, which writes `any` + `UNDECIDED` and an `undecided` rule with the
quote — visible to a human, never resolved to "no requirement".

### A programme page the reader could not see

`readable_text` reads whatever HTML it is handed, and a served page is often a shell whose
criteria render client-side.

- **Soft 404s.** Retired JASSO URLs redirect on-origin
  to `/notfound.html` (52,998 bytes, 265 readable characters). It passes `require_same_origin` and is archived as
  the page. Any probe of this path must print its final URL.
  **Detected since 2026-09-18, in two checks, and the flag is now a reason.**
  `OfficialSourceSnapshot.readability` is `OK | SHELL | SOFT_404 | UNPARSEABLE` in place of the old `unreadable`
  boolean, because "we could not read it" and "it says nothing" are the same silence from outside and
  each cause needs a different answer. The checks are `reader.redirected_to_a_not_found_page` (the
  final URL's path changed and is /404-shaped — free, URLs only, so a thin real page and a programme
  about error analysis cannot trip it; measured live 2026-09-18, a missing path under jasso.go.jp
  lands on `/notfound.html` at **HTTP 200**, which the fetch layer cannot see as an error) and a per-host control fetch of `reader._CONTROL_PATH`, cached a day,
  whose `content_digest` is compared with the page's. A control that redirected off that path is
  discarded rather than trusted — accepting it would mark every read of wherever it landed a soft 404.
  **Consequence for tests: a fake `retrieve=` that returns the same body for every URL now describes
  a host whose every page is its not-found page**, and the read is correctly recorded `SOFT_404`
  instead of derived. The doubles in `tests/research/test_reader.py` and `tests/documents/test_derive.py`
  raise `SourceBlocked` for that path, which is what a polite host does.
- **The floor marks short real pages unreadable.** Sciences Po's Eiffel page is 467,380 bytes and
  1,093 readable characters, all real prose, so it derives nothing. That is loud, not silent, but it is
  a coverage loss on the long tail. Do not lower the floor on such pages alone: without a render
  that demonstrably adds text, a short page and a shell whose script failed look the same.
- **A shell page and a page that genuinely states no requirements are still
  indistinguishable from the outside**, and `read_program_page` still keeps the previous rows in
  both cases. That hazard is about silence, not about JS rendering, so a vendor closing the
  rendering gap does not close it — a page a vendor also returns empty still needs `readable_text`'s
  1,500-character `SHELL` floor (`egress._MIN_READABLE_CHARS`) and a human eventually confirming which case it is.
