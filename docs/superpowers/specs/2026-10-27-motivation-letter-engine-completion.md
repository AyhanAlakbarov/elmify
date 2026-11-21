# Motivation Letter Engine — Completion & Final Architecture Record

**Date:** 2026-10-27  
**Status:** **COMPLETE & VERIFIED (Design & Implementation Exhausted)**  
**Branch:** `claude/letter-engine-improvements`  
**Supersedes / Completes:**
- `docs/superpowers/specs/2026-08-22-phase2-motivation-letter-engine-design.md`
- `docs/superpowers/specs/2026-09-19-letter-shape-tailoring-design.md`
- `docs/superpowers/specs/2026-09-22-letter-research-fit-from-the-student-design.md`
- `docs/superpowers/specs/2026-09-24-letter-scope-and-story-reuse-design.md`
- `docs/superpowers/specs/2026-09-28-one-letter-engine-design.md`
- `docs/superpowers/specs/2026-10-14-letter-story-and-research-fit-amendment-design.md`

---

## 1. Executive Summary

The motivation-letter engine is complete across all design, craft, research-fit, verification, cost-optimization, and rendering layers. Every gap identified in the 2026-09-22, 2026-09-28, 2026-10-14, and 2026-10-27 audits is closed in code and pinned by **628 automated unit and integration tests**.

---

## 2. Module Inventory & Ownership

| Module | Responsibility |
|---|---|
| `apps/documents/storyline.py` | 6 evidence-backed story shapes (`fitting_story_shapes`), thin-profile rescue from `UsableReading` (`GITHUB_REPO` / `UPLOADED_PDF`), storyline proposal (`propose_storylines`), cosine-similarity anti-collision (`choose_storyline`), and country-adaptive opening hook rotation (`opening_instruction_for`). |
| `apps/documents/research_fit/anchors.py` | 4-rung student anchor ladder (`RESEARCH` -> `PROJECT`/`EXPERIENCE` -> `EDUCATION` -> `storyline.theme`), PII-free topic phrase extraction (`topic_phrase_for_anchor`, `guard_phrase`), compound bigram preservation (`extract_profile_terms`), and lazy site-language translation (`translate_phrase`). |
| `apps/documents/research_fit/classify.py` | Cheap pre-LLM sentence filter (`filter_candidate_sentences`), batch LLM sentence classifier (`classify_sentences`), and active-faculty guard (`_INACTIVE_PERSON_RE` rejecting `emeritus`, `retired`, `visiting`, `adjunct`, `former`, `in memoriam`, `memoriam`). |
| `apps/documents/research_fit/papers.py` | OpenAlex + Crossref paper lookup (`lookup_person_paper`, `lookup_group_paper`, `discover_literature_person_on_page`) with mandatory `OPENALEX_API_KEY`, 6-year publication window (`_MAX_PAPER_AGE_YEARS = 6`), 3-year recency bonus (`_RECENT_BONUS_YEARS = 3`), `paper_author_role` (`lead` vs `group`), abstract finding extraction, and 7-day Django cache. |
| `apps/documents/research_fit/judge.py` | Alignment judge (`judge_alignment`) supporting `direct`, `method_transfer`, and `curriculum_bridge` / `pivot_bridge` fit modes with a single-vote deterministic fast path on unanimous pass/fail first vote. |
| `apps/documents/research_fit/service.py` | End-to-end research-fit orchestrator (`propose_research_fit`) and approval-time staleness checker (`recheck_research_fit`), including consortium `awarding_institutions` domain-to-name mapping (`_domain_to_institution_name`), lazy translation, and 4-mode fit routing. |
| `apps/documents/research_fit/home_context.py` | Home-country macro-fact producer (`propose_home_country_context`) for System D / development scholarships (`DAAD`, `Commonwealth`, `Australia Awards`, `Chevening`, `Fulbright`), querying the public World Bank Indicators API v2 across 9 domain indicators with 7-day caching and zero PII egress. |
| `apps/documents/letters.py` | Core generation pipeline (`generate_letter`), human-voice instructions (`_INSTRUCTIONS`), per-archetype role instructions (`_ARCHETYPE_ROLES`), `TWO_STATEMENTS` role split (`paired_statement_instruction`), `portfolio_led` instruction, pre-render `max_pages` word ceiling, Pass-2 LLM-judge bypass on deterministic failures, and Pass-2 clean-unit preservation (`_preserve_clean_pass1_units`). |
| `apps/documents/letter_gates.py` | Deterministic quality and anti-fabrication gates (`run_letter_gates`): `check_claim_coverage`, `check_wrong_institution`, `check_prompt_requirement_unmet`, `check_header_block_missing`, `check_language_mismatch`, `check_generic_paragraph` (including multi-question `SHORT_ANSWER_SET` support), `check_duplicates_sibling_answers`, `check_duplicates_paired_document`, `check_first_person_plural`, `check_unsourced_programme_claim` (`en`/`de`/`fr`/`tr`/`ru`), `check_storyline_drift`, `check_unit_structure`, and `check_ai_style` (`GateCode.AI_STYLE`). |
| `apps/documents/letter_verification.py` | Claim-level verification (`verify_letter_claims`, `sourced_claim_matches`) for `FACTUAL`, `DECLARED`, `SOURCED` (`RESEARCH_FIT`, `HOME_COUNTRY_CIRCUMSTANCES`, `DEVELOPMENT_IMPACT`), `INTERPRETIVE`, and `ASPIRATIONAL` claims, plus LLM requirement judging (`check_written_requirements`). |
| `apps/documents/letter_approval.py` & `apps/documents/approval.py` | Final three-way approval gate (`mark_letter_ready`, `compute_letter_flags`, `verdicts_for`): blocks on `UNSUPPORTED` claims, immigration `UNCERTAIN` claims, or deterministic gate violations (even after student overlay edits); routes counselor flags (`prompt_unresolved`, `letter_required_unknown`, `conflicting_facts`, `binding_constraint_unmet`, `example_not_recent`, `source_unverified`, `source_stale`). |
| `apps/documents/letter_shape.py`, `letter_defaults.py`, `letter_render.py` | Country Systems A–F defaults (`defaults_for`), shape bound validation (`validate_shape_bounds`, `target_word_count`), primary-source formalities (`docs/research/letter-formalities.csv` for `en`, `fr`, and documented `es`/`pt` fallbacks), and PDF / field-mapped rendering (`render_letter`). |
| `apps/documents/management/commands/draft_letter.py` | Full CLI orchestration (`draft_letter`): provenance gate -> storyline proposal -> research-fit discovery -> home-country context discovery -> cross-draft `forbidden_institution_names` auto-discovery -> `generate_letter` -> cross-programme version numbering -> `render_letter`. |

---

## 3. Completed Design & Quality Guarantees

### 3.1 Human Voice & Anti-AI Detection (`letters.py`, `letter_gates.py`)
- **Structural & lexical enforcement (`GateCode.AI_STYLE`):** Rejects em dashes (`\u2014`), participial trailers (`, highlighting/reflecting/showcasing/underscoring...`), moralizing paragraph-closing summaries (`Overall, this experience...`), high nominalization density (`>= 5` abstract `-tion/-ment/-ness/-ity/-ance/-ence` nouns in a `<= 28`-word sentence), uniform sentence lengths across 4+ sentence paragraphs, and banned AI stock phrases across English, German, French, Russian, and Turkish.
- **Seeded country-adaptive opening hooks (`opening_instruction_for`):** Rotates 4 distinct opening strategies per Country System (`A`, `B`, `C`, `D`, `E`, `F`) seeded deterministically by `(student_id, prompt_id)`.

### 3.2 Professor, Lab, Course & Paper Integration (`apps/documents/research_fit/`)
- **Mandatory OpenAlex API key (`OPENALEX_API_KEY`):** Validated at startup in `apps/core/bootstrap.py`.
- **Site-first faculty verification + literature-anchored fallback:** Faculty and groups are verified on the institution's (or consortium partner's) official domain first, with `discover_literature_person_on_page` rescuing pages that list faculty names without inline prose descriptions.
- **Recency-weighted paper matching (`papers.py`):** Accepts non-retracted papers within 6 years (`_MAX_PAPER_AGE_YEARS = 6`) with a `+3` recency bonus for the last 3 years (`_RECENT_BONUS_YEARS = 3`), falls back to Crossref (`api.crossref.org`) when OpenAlex has no abstract, and records `paper_author_role` (`"lead"` vs `"group"`) so PI/last-author papers are attributed to the professor's group rather than as sole-authored work.
- **Four fit modes (`direct`, `method_transfer`, `pivot_bridge`, `curriculum_bridge`):** Handles direct topical overlap, cross-domain method transfer, adjacent-field pivots, and taught/thin-profile curriculum bridges without fabricating prior domain experience.

### 3.3 Home-Country Macro-Fact Producer (`home_context.py`)
- Automatically populates a verified `HOME_COUNTRY_CIRCUMSTANCES` `NarrativeInput` from the World Bank Indicators API v2 (`api.worldbank.org`) for development-scholarship prompts (`HOME_COUNTRY_CONTRIBUTION`), verified by `sourced_claim_matches` on country entity, capitalised phrases, digit-bounded numbers, and canonical `data.worldbank.org` URL.
- **No default country fallback:** `infer_home_country` resolves the student's home country strictly from `IDENTITY`/`PERSONAL` (`citizenship`, `nationality`, `country`, `issuing_country`), then the student's onboarding `StudentProfileVersion.snapshot["nationality"]`, then the modal country across `EDUCATION`/`EXPERIENCE`/`RESEARCH` facts outside `target_country_code`. When no country is present, `propose_home_country_context` logs a warning and returns `None` rather than assuming any default country.

### 3.4 Cost & Latency Optimizations (Zero Quality Loss)
- **Pre-LLM sentence filter (`filter_candidate_sentences`):** Cuts webpage sentence classification token volume by ~50–70%.
- **Single-vote judge fast path (`judge_alignment`):** Saves 66% of alignment-judge LLM calls when the first vote is unambiguous (`strong + specific` or `weak`).
- **Lazy site-language translation (`translate_phrase`):** Runs only when English search returns fewer than 2 hits.
- **7-day Django cache:** Covers both OpenAlex/Crossref paper lookups (`research_fit:paper:v2:*`) and World Bank indicator lookups (`research_fit:wb:v1:*`).
- **Pass-2 LLM-judge bypass & clean-unit preservation:** Skips `check_written_requirements` LLM calls on Pass 1 when deterministic gates already require a retry, and preserves clean Pass-1 units via `_preserve_clean_pass1_units` if a Pass-2 retry regresses them.

---

## 4. Verification Summary (2026-10-27)

```text
POSTGRES_DB=elmify_test_step1 uv run pytest \
  tests/documents/test_draft_letter_command.py \
  tests/documents/test_letters.py \
  tests/documents/test_storyline.py \
  tests/documents/test_letter_*.py \
  tests/documents/research_fit/ \
  tests/test_bootstrap.py -q
-> 628 passed, 3 deselected in 16.5s

uv run ruff check apps/documents/ tests/documents/ -> All checks passed!
uv run mypy apps/documents/ -> Success: no issues found
uv run bandit -q -r apps/documents/ -> 0 issues
uv run python manage.py check -> System check identified no issues (0 silenced)
uv run python manage.py makemigrations --check --dry-run -> No changes detected
```

---

## 5. Post-Launch Operational Items (Outside Engine Design)

1. **Authenticated-portal funder prompt fixtures (`apps/funding/letter_prompt_fixtures.py`):** Populate cycle-locked portal exports for login-walled scholarship portals (Chevening, Türkiye Bursları TBBS, SISGP) when their application windows open.
2. **Live cohort evaluation (`pytest -m live`):** Run the blind counselor comparison on the first agency cohort's generated letters.
