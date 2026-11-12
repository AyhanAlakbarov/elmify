# Admission & Scholarship Probability Estimation, 3rd-Party LinkedIn Winner Benchmarking, and Catalogue Isolation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Estimate and display `"We estimate that there is an ~X% chance"` on every recommended programme and scholarship card from Day 1 (combining base selectivity priors, student transcript/profile margins, 3rd-party LinkedIn winner similarity, and Empirical Bayes / ML outcome calibration), while keeping the global catalogue and winner cohorts accessible to Elmify staff and isolated from B2B customers.

**Architecture:**
1. **`WinnerCohortProfile` (`apps/research/models.py`, `_PLATFORM_TABLES`):** Stores PII-free aggregate distributions of past winners scraped via a pluggable 3rd-party LinkedIn provider (`apps/research/winner_scraper.py`). Protected by `platform_operator_select` / `platform_operator_update` / `runtime_engine_write` RLS so `runtime_engine` and Elmify staff (`PlatformAgency` + `PLATFORM_ADMIN` + MFA) can read it (including at `/platform/catalogue/`), while B2B agencies get zero rows at the DB layer and `403 PermissionDenied` at the view layer.
2. **`OutcomeCalibrationRecord` (`apps/funding/models.py`, `_SHARED_TABLES`) & `RecommendationCandidate` fields:** `RecommendationCandidate` carries `estimated_chance_pct` (`PositiveSmallIntegerField`) and `calibration_features` (`JSONField`, both marked `REDACT` in `apps/audit/redaction.py`). `OutcomeCalibrationRecord` is a shared-catalogue table (`runtime_web` revoked) synced by `runtime_engine` from non-erased decided `Application` rows.
3. **Probability Estimator (`apps/funding/probability.py`) & Card Rendering:** Pure estimator computing `estimated_chance_pct` (`1`–`95%` for competitive routes, `100%` for `AUTOMATIC_ON_ADMISSION` benefits) from base rate + profile/transcript margin + LinkedIn winner archetype similarity + Empirical Bayes / logistic calibration over `OutcomeCalibrationRecord` rows, copied onto `RecommendationCandidate` in `apps/research/services.py::_publish` and rendered on `templates/student/_candidate.html`, `templates/student/_card.html`, and `templates/student/programme.html`.

**Tech Stack:** Python 3.14, Django 5.2, PostgreSQL Row-Level Security (`runtime_web` / `runtime_engine`), `pytest`.

**Spec:** `docs/superpowers/specs/2026-10-29-admission-probability-and-winner-benchmark-design.md`

## Global Constraints
- Card copy must be exact: `"We estimate that there is an ~{pct}% chance"` when `estimated_chance_pct` is set, and omitted when `None` or after an application has a recorded decision (`application.outcome != ""`).
- Competitive probabilities are clamped to `[1, 95]`; only `AUTOMATIC_ON_ADMISSION` routes may reach `100`.
- `WinnerCohortProfile` must never store personal names, LinkedIn URLs, profile IDs, or free-text bios.
- `Program`, `FundingOpportunity`, and `OutcomeCalibrationRecord` remain in `_SHARED_TABLES` (`catalogue_tables()`) with all `runtime_web` privileges revoked; `WinnerCohortProfile` joins `_PLATFORM_TABLES` with `platform_operator_select`, `platform_operator_update`, and `runtime_engine_write`.
- Both `estimated_chance_pct` and `calibration_features` on `RecommendationCandidate` must be registered in `REDACT["funding.RecommendationCandidate"]` in `apps/audit/redaction.py`.

## Review Focus
1. **Unconfigured or failing 3rd-party LinkedIn API (`LINKEDIN_WINNER_PROVIDER_URL` unset or HTTP 5xx):** `sync_winner_cohort_for_program` / `sync_winner_cohort_for_opportunity` logs the provider failure and returns `None` without crashing or inventing a cohort; probability estimation degrades gracefully to base-rate + student margin.
2. **PII fields present in 3rd-party LinkedIn JSON payload (`full_name`, `linkedin_url`, `public_identifier`, `headline`):** `aggregate_winner_cohort` strips all PII and persists only ISO-2 country counts, normalized degree field tokens, degree level counts, experience quartiles, and research signal rate.
3. **Student with `BORDERLINE` coursework vs. `SATISFIED` coursework and high GPA:** `estimate_program_admission_chance` produces a strictly lower `estimated_chance_pct` for the `BORDERLINE` student than for the `SATISFIED` student on the same programme.
4. **Outcome correction (`ADMITTED` -> `REJECTED`) and GDPR erasure (`redact_student`):** `sync_outcome_calibration_records()` updates `OutcomeCalibrationRecord.won` in place when an outcome is corrected, and deletes the `OutcomeCalibrationRecord` row when the student is redacted/erased or the outcome is cleared to `""`.
5. **B2B `OWNER` and `COUNSELOR` attempting to access `/platform/catalogue/` or query `WinnerCohortProfile` / `Program` under `runtime_web`:** `/platform/catalogue/` raises `403 PermissionDenied` for B2B users, `runtime_web` under a B2B tenant sees `0` rows from `research_winnercohortprofile` and raises `InsufficientPrivilege` on `funding_outcomecalibrationrecord` and `funding_program`.

---

### Task 1: Database Models, RLS Policies, and Redaction Registry (`WinnerCohortProfile`, `OutcomeCalibrationRecord`, `RecommendationCandidate`)

**Files:**
- Modify: `apps/research/models.py`
- Create: `apps/research/migrations/0032_winner_cohort_profile.py`
- Create: `apps/research/migrations/0033_winner_cohort_profile_rls.py`
- Modify: `apps/funding/models.py:145-185`
- Create: `apps/funding/migrations/0065_probability_and_outcome_calibration.py`
- Create: `apps/funding/migrations/0066_outcome_calibration_rls.py`
- Modify: `apps/audit/redaction.py:228-231`
- Modify: `tests/tenancy/test_database_isolation.py:80-105`

**Interfaces:**
- Produces:
  - `apps.research.models.WinnerCohortProfile` (`program_id`, `opportunity_id`, `target_kind`, `target_name`, `holder_name`, `country_code`, `sample_size`, `origin_country_counts`, `prior_degree_fields`, `prior_degree_levels`, `work_experience_months_p25`, `work_experience_months_median`, `work_experience_months_p75`, `research_signal_rate`, `source_provider`, `last_synced_at`)
  - `apps.funding.models.OutcomeCalibrationRecord` (`application_id`, `program`, `opportunity`, `country_code`, `family`, `route`, `predicted_chance_pct`, `feature_vector`, `won`, `recorded_at`)
  - `RecommendationCandidate.estimated_chance_pct: int | None` and `RecommendationCandidate.calibration_features: dict[str, Any]`

- [ ] **Step 1: Add `WinnerCohortProfile` to `apps/research/models.py` and `OutcomeCalibrationRecord` + `RecommendationCandidate` fields to `apps/funding/models.py`**
- [ ] **Step 2: Create migrations `0032_winner_cohort_profile.py`, `0033_winner_cohort_profile_rls.py`, `0065_probability_and_outcome_calibration.py`, and `0066_outcome_calibration_rls.py`**
- [ ] **Step 3: Register `estimated_chance_pct` and `calibration_features` in `REDACT["funding.RecommendationCandidate"]` in `apps/audit/redaction.py`, and add `funding_outcomecalibrationrecord` to `_SHARED_TABLES` and `research_winnercohortprofile` to `_PLATFORM_TABLES` in `tests/tenancy/test_database_isolation.py`**
- [ ] **Step 4: Run `pytest --reuse-db tests/tenancy/test_database_isolation.py tests/tenancy/test_catalog_grants.py tests/audit/test_redaction.py`**
  Expected: PASS (with `--create-db` on first migration run)

---

### Task 2: 3rd-Party LinkedIn Winner Scraper & Anonymised Cohort Aggregator (`apps/research/winner_scraper.py`)

**Files:**
- Create: `apps/research/winner_scraper.py`
- Create: `apps/research/management/commands/sync_winner_cohorts.py`
- Test: `tests/research/test_winner_scraper.py`

**Interfaces:**
- Consumes: `WinnerCohortProfile`, `Program`, `FundingOpportunity`
- Produces:
  - `RawWinnerProfile(origin_country: str, prior_degree_fields: tuple[str, ...], prior_degree_level: str, work_experience_months: int | None, has_research_signal: bool)`
  - `WinnerSearchProvider` protocol & `HttpThirdPartyLinkedInProvider` (reads `LINKEDIN_WINNER_PROVIDER_URL` and `LINKEDIN_WINNER_API_KEY` from `os.environ`)
  - `aggregate_winner_cohort(profiles: Sequence[RawWinnerProfile | Mapping[str, Any]]) -> dict[str, Any]`
  - `sync_winner_cohort_for_program(program: Program, *, provider: WinnerSearchProvider | None = None) -> WinnerCohortProfile | None`
  - `sync_winner_cohort_for_opportunity(opportunity: FundingOpportunity, *, provider: WinnerSearchProvider | None = None) -> WinnerCohortProfile | None`

- [ ] **Step 1: Write failing tests in `tests/research/test_winner_scraper.py`** covering PII stripping, quartile & field distribution aggregation, graceful degradation when provider is unconfigured or errors, and upsert into `WinnerCohortProfile`.
- [ ] **Step 2: Implement `apps/research/winner_scraper.py` and `apps/research/management/commands/sync_winner_cohorts.py`**
- [ ] **Step 3: Run `pytest --reuse-db tests/research/test_winner_scraper.py`**
  Expected: PASS

---

### Task 3: Cold-Start -> Empirical Bayes -> ML Probability Estimator & Outcome Calibration Sync (`apps/funding/probability.py`)

**Files:**
- Create: `apps/funding/probability.py`
- Modify: `apps/funding/pack.py` (`PackedApplication.estimated_chance_pct`, `PackedAward.estimated_chance_pct`)
- Modify: `apps/research/spine.py` (compute `estimated_chance_pct` and `calibration_features` for programmes and awards)
- Modify: `apps/research/services.py` (copy `estimated_chance_pct` and `calibration_features` onto `RecommendationCandidate` in `_publish`)
- Test: `tests/funding/test_probability.py`

**Interfaces:**
- Consumes: `CandidateFacts`, `AwardCandidateFacts`, `StudentProfileSnapshot`, `WinnerCohortProfile`, `OutcomeCalibrationRecord`
- Produces:
  - `ProbabilityEstimate(chance_pct: int, features: dict[str, float])`
  - `estimate_program_admission_chance(program: Program, facts: CandidateFacts, profile: StudentProfileSnapshot, *, statements: Sequence[ProgramStatement] = (), winner_cohort: WinnerCohortProfile | None = None, calibration_rows: Sequence[OutcomeCalibrationRecord] = (), today: date | None = None) -> ProbabilityEstimate`
  - `estimate_scholarship_chance(award: FundingOpportunity, facts: AwardCandidateFacts, profile: StudentProfileSnapshot, *, winner_cohort: WinnerCohortProfile | None = None, calibration_rows: Sequence[OutcomeCalibrationRecord] = (), today: date | None = None) -> ProbabilityEstimate`
  - `sync_outcome_calibration_records() -> int`

- [ ] **Step 1: Write failing tests in `tests/funding/test_probability.py`** covering:
  - Rule-based (`DE`) vs. selective (`FR`/EMJM) base rates
  - Student coursework `SATISFIED` vs. `BORDERLINE` and GPA margin shifts
  - LinkedIn `WinnerCohortProfile` archetype similarity boost vs. mismatch penalty
  - Empirical Bayes Beta-Binomial update (1–49 `OutcomeCalibrationRecord` rows) and logistic calibration (50+ rows)
  - `sync_outcome_calibration_records()` upserting on `ADMITTED`/`REJECTED`, updating on `correct_outcome`, and deleting on `redact_student` erasure
- [ ] **Step 2: Implement `apps/funding/probability.py` and wire `estimated_chance_pct` and `calibration_features` through `pack.py`, `spine.py`, and `apps/research/services.py`**
- [ ] **Step 3: Run `pytest --reuse-db tests/funding/test_probability.py tests/funding/test_spine.py`**
  Expected: PASS

---

### Task 4: Card Display (`"We estimate that there is an ~X% chance"`) and `/platform/catalogue/` Staff Console with B2B Isolation Verification

**Files:**
- Modify: `apps/dashboard/board.py` (`Card.chance_line: str = ""`)
- Modify: `templates/student/_candidate.html`
- Modify: `templates/student/_card.html`
- Modify: `templates/student/programme.html`
- Modify: `apps/research/urls.py` (add `path("platform/catalogue/", views.catalogue_overview, name="platform-catalogue")`)
- Modify: `apps/research/views.py` (add `catalogue_overview` gated by `_operator(request)`)
- Create: `templates/research/catalogue_overview.html`
- Test: `tests/research/test_catalogue_access_isolation.py`

**Interfaces:**
- Consumes: `RecommendationCandidate.estimated_chance_pct`, `WinnerCohortProfile`, `_operator(request)`
- Produces:
  - `Card.chance_line`: `"We estimate that there is an ~{pct}% chance"` (when `candidate.estimated_chance_pct` is set and `application.outcome == ""`)
  - `/platform/catalogue/` view accessible only to Elmify `PlatformAgency` `PLATFORM_ADMIN` with verified MFA

- [ ] **Step 1: Write failing tests in `tests/research/test_catalogue_access_isolation.py`** asserting:
  - Card rendering shows `"We estimate that there is an ~X% chance"` on both `_candidate.html` and `_card.html`
  - Elmify staff (`PlatformAgency` + `PLATFORM_ADMIN` + MFA) receives `200 OK` on `/platform/catalogue/` and sees `WinnerCohortProfile` rows
  - B2B `OWNER`, B2B `COUNSELOR`, and `STUDENT` receive `403 PermissionDenied` on `/platform/catalogue/`
  - B2B `COUNSELOR` can access their assigned student's board (`200 OK`) and sees the student's `chance_line`, cannot access an unassigned student (`404`/`403`), and under `runtime_web` sees `0` rows in `research_winnercohortprofile` and raises `InsufficientPrivilege` on `funding_program`, `funding_fundingopportunity`, and `funding_outcomecalibrationrecord`
- [ ] **Step 2: Update `apps/dashboard/board.py`, card templates, and `apps/research/views.py` + `apps/research/urls.py` + `templates/research/catalogue_overview.html`**
- [ ] **Step 3: Run `pytest --reuse-db tests/research/test_catalogue_access_isolation.py tests/dashboard/ tests/funding/` and `ruff`, `mypy`, `bandit`**
  Expected: PASS
