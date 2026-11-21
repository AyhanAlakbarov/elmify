# Admission & Scholarship Probability Estimation, 3rd-Party LinkedIn Winner Benchmarking, and Catalogue Access Isolation

**Date:** 2026-10-29  
**Status:** Draft for approval  
**Owner decisions incorporated:**
1. **Card surface:** Display a single, plain sentence on each recommended programme and scholarship card: `"We estimate that there is an ~X% chance"` (e.g., `"We estimate that there is an ~65% chance of admission"` for a programme card, `"We estimate that there is an ~8% chance for this scholarship"` for an award card).
2. **Cold-start to ML progression:** Compute `X%` on Day 1 with zero historical ML rows by combining official selectivity signals, the student's academic/transcript/language/experience margin above the published bars, and 3rd-party LinkedIn winner similarity; automatically transition to empirical Bayes (Beta-Binomial shrinkage) and calibrated ML as student and B2B application outcomes accumulate.
3. **3rd-party LinkedIn winner ingestion:** Use a pluggable 3rd-party LinkedIn/people search provider (configured via environment variables) to ingest past scholarship/programme winners, stripping all personal identifiers at ingestion and storing only anonymised aggregate cohort distributions (`WinnerCohortProfile`).
4. **Access control & catalogue isolation:**
   - **Elmify internal staff** (`PlatformAgency` + `Membership.Role.PLATFORM_ADMIN` / Django `is_staff` + verified MFA) have full access to everything (the global scholarship and programme catalogue, winner cohort profiles, calibration datasets, and operator consoles).
   - **B2B customers (`OWNER` and `COUNSELOR` memberships in tenant agencies)** have access **only to their own customer students** (and the tenant-scoped recommendation/application cards generated for those students). B2B users have **zero access** to browse, query, search, or export the global database of stored scholarships, programmes, or winner cohorts.

---

## 1. Intent & Why

Students and B2B counsellors need an immediate, intuitive sense of how realistic each recommended programme or scholarship is for a specific student profile (`~X%` chance), without cluttering the card with statistical jargon. At the same time:
- On Day 1, Elmify has **no first-party historical `(profile, applied-to, outcome)` training rows**, so a naive ML model cannot be trained yet.
- Scraping LinkedIn for past winners via a 3rd-party API provides rich data on **what winners look like** ($P(\text{Profile } X \mid \text{Win})$: prior degree fields, prior institutions, work experience duration, research/publication signals, origin country representation), but LinkedIn never shows rejected applicants ($Y = 0$). Using LinkedIn winner counts alone as an acceptance rate would suffer from survivorship bias.
- Combining **base-rate selectivity priors** (from published selection rates, `awards ÷ applicants`, admission regime `zulassungsfrei` vs. competitive quota, and student margin above the minimum bar) with **LinkedIn winner archetype similarity** ($P(X \mid \text{Win})$ likelihood ratio) and **first-party B2B/B2C outcome capture** produces an honest, bounded `estimated_chance_pct` (`1`–`95%`) from Day 1 that seamlessly sharpens as outcomes are recorded.
- Finally, the global scholarship and programme catalogue (plus scraped LinkedIn winner cohorts) is Elmify's core intellectual property. B2B agencies must only ever see the cards generated for their own students, while Elmify staff can inspect and manage the entire catalogue.

---

## 2. Goals, Non-Goals, and Anti-Goals

### Goals
1. **Pure, deterministic cold-start probability estimator (`apps/funding/probability.py`):**
   - Computes `estimated_chance_pct: int` (clamped to `[1, 95]`) for both a programme (`estimate_program_admission_chance`) and a scholarship (`estimate_scholarship_chance`).
   - Incorporates:
     - Base rate from published selection rate / `awards ÷ applicants` / scheme family & route (`AUTOMATIC_ON_ADMISSION`, `CONSIDERED_WITH_ADMISSION`, `STUDENT_APPLIES`, `INSTITUTION_NOMINATES`, `HOME_GOVERNMENT_NOMINATES`) / programme admission regime.
     - Student margin above published bars from `apps/funding/transcript_eligibility.py` and `apps/funding/eligibility.py` (converted GPA / Bavarian grade margin, coursework ECTS coverage ratio, IELTS/TOEFL margin, work experience margin).
     - Winner archetype similarity (`0.0` to `1.0`) comparing the student's `StudentProfileSnapshot` against the anonymised `WinnerCohortProfile` scraped from 3rd-party LinkedIn data.
     - Empirical Bayes / Beta-Binomial posterior update + calibrated logistic model when first-party `OutcomeCalibrationRecord` rows exist for that programme, opportunity, or `(country_code, family)` corridor.
2. **Pluggable 3rd-Party LinkedIn Winner Scraper (`apps/research/winner_scraper.py`):**
   - Defines a `WinnerSearchProvider` protocol with a default HTTP JSON adapter configured via environment variables (`LINKEDIN_WINNER_PROVIDER_URL`, `LINKEDIN_WINNER_API_KEY`) supporting 3rd-party providers (Proxycurl / People Data Labs / Bright Data / Exa).
   - Strips all PII (names, LinkedIn URLs, headlines, profile photos, exact employer names) in memory before persistence, saving only aggregate counts and distributions on `WinnerCohortProfile` in the catalogue schema.
3. **Single-line card display:**
   - Copies `estimated_chance_pct` onto tenant-scoped `RecommendationCandidate` at pack publish time (`apps/research/services.py::_publish`).
   - Renders `"We estimate that there is an ~{{ candidate.estimated_chance_pct }}% chance"` on `templates/student/_candidate.html` and `"We estimate that there is an ~{{ card.estimated_chance_pct }}% chance"` on `templates/student/_card.html` (and `templates/student/programme.html`) whenever `estimated_chance_pct` is present.
4. **First-party ML calibration capture (`OutcomeCalibrationRecord`):**
   - Whenever an application or scholarship outcome (`ADMITTED`, `ADMITTED_CONDITIONAL`, `REJECTED`) is recorded via `apps/portals/outcome.py`, records an anonymised feature vector + outcome row for model calibration and training.
5. **Strict Access Control & Catalogue Isolation:**
   - Keep `Program`, `FundingOpportunity`, `WinnerCohortProfile`, and `OutcomeCalibrationRecord` as **catalogue-tier tables** (no `SELECT` grant for `runtime_web` used by tenant B2B/student requests, or gated exclusively behind Elmify platform staff checks).
   - Provide an Elmify-staff-only catalogue & winner-cohort inspection view under `/platform/catalogue/` gated by `_operator(request)` (`PlatformAgency` host + `Membership.Role.PLATFORM_ADMIN` or `user.is_staff` + `require_staff_mfa`), and verify via tests that B2B `OWNER` and `COUNSELOR` users receive `403 PermissionDenied` on `/platform/*` and cannot query catalogue tables or unassigned students.

### Non-Goals
- Storing raw LinkedIn profiles, full names, or LinkedIn URLs of third-party individuals (prohibited for privacy/GDPR compliance).
- Exposing multi-number confidence intervals or technical ML feature weights on the student/counsellor card UI.

### Anti-Goals (What would make this a failure even if it works)
- Showing `0%` or `100%` for any competitive application (probabilities are clamped to `1%–95%`, except `100%` for `AUTOMATIC_ON_ADMISSION` benefits conditional on admission).
- Treating LinkedIn winner count alone as the acceptance rate denominator.
- Allowing a B2B `OWNER` or `COUNSELOR` to list, search, or export `Program`, `FundingOpportunity`, or `WinnerCohortProfile` rows across the catalogue, or to view students not belonging to their tenant / assignment.

---

## 3. Data Model & Schema Changes

### 3.1 Catalogue & Platform Models (`apps/research/models.py` / `apps/funding/models.py`)

1. **`WinnerCohortProfile` (`apps/research/models.py` — Platform-tier table in `_PLATFORM_TABLES`):**
   - *Builder call (from builder-check review):* Placed in `_PLATFORM_TABLES` (`research_winnercohortprofile`) with the three platform RLS policies (`platform_operator_select`, `platform_operator_update`, `runtime_engine_write` gated on `current_setting('app.tenant_id', true)::uuid IN (SELECT agency_id FROM research_platformagency)`), using plain UUID columns (`program_id`, `opportunity_id`) rather than ORM ForeignKeys into `_SHARED_TABLES`. This allows `runtime_engine` to read/write it in the spine and allows Elmify staff on `PlatformAgency` to inspect it at `/platform/catalogue/` under `runtime_web`, while B2B agencies get `0` rows from Postgres RLS and `403 PermissionDenied` at `_operator(request)`.
   - `id`: `UUIDField(primary_key=True, default=uuid4)`
   - `program_id`: `UUIDField(null=True, blank=True, unique=True)`
   - `opportunity_id`: `UUIDField(null=True, blank=True, unique=True)`
   - `target_kind`: `CharField(max_length=16)` — `"PROGRAM"` or `"OPPORTUNITY"`
   - `target_name`: `CharField(max_length=300)` — denormalized programme or scholarship name for `/platform/catalogue/`
   - `holder_name`: `CharField(max_length=300, blank=True, default="")` — denormalized institution or funder name
   - `country_code`: `CharField(max_length=2, blank=True, default="")`
   - `sample_size`: `PositiveIntegerField(default=0)` — number of anonymised winner profiles aggregated
   - `origin_country_counts`: `JSONField(default=dict, blank=True)` — `{"AZ": 4, "TR": 7, "IN": 12}`
   - `prior_degree_fields`: `JSONField(default=dict, blank=True)` — normalized field token/category counts, e.g. `{"computer science": 18, "mathematics": 7, "chemistry": 3}`
   - `prior_degree_levels`: `JSONField(default=dict, blank=True)` — `{"BACHELOR": 20, "MASTER": 8}`
   - `work_experience_months_p25`: `PositiveIntegerField(null=True, blank=True)`
   - `work_experience_months_median`: `PositiveIntegerField(null=True, blank=True)`
   - `work_experience_months_p75`: `PositiveIntegerField(null=True, blank=True)`
   - `research_signal_rate`: `DecimalField(max_digits=5, decimal_places=4, null=True, blank=True)` — fraction (`0.0000`–`1.0000`) of winners with research/publication/thesis keywords
   - `source_provider`: `CharField(max_length=64, blank=True, default="")` — e.g. `"linkedin_3p"`
   - `last_synced_at`: `DateTimeField(auto_now=True)`
   - **Constraint:** Exactly one of `program_id` or `opportunity_id` is non-null (`winner_cohort_target_xor`).

2. **`OutcomeCalibrationRecord` (`apps/funding/models.py` — Shared-catalogue table in `_SHARED_TABLES`):**
   - *Builder call (from builder-check review):* Because `correct_outcome` in `apps/portals/outcome.py` runs synchronously on `runtime_web` (which has zero grants on `_SHARED_TABLES`), `RecommendationCandidate` stores the student's numeric `calibration_features` JSON at pack-publish time (`_publish`), and `runtime_engine` syncs `OutcomeCalibrationRecord` via `sync_outcome_calibration_records()` (keyed by `application_id` so outcome changes update in place, and redacted/erased applications are deleted from `OutcomeCalibrationRecord`).
   - `id`: `UUIDField(primary_key=True, default=uuid4)`
   - `application_id`: `UUIDField(unique=True)` — upsert/delete key synced from non-erased decided `Application` rows
   - `program`: `ForeignKey(Program, null=True, blank=True, on_delete=models.SET_NULL)`
   - `opportunity`: `ForeignKey(FundingOpportunity, null=True, blank=True, on_delete=models.SET_NULL)`
   - `country_code`: `CharField(max_length=2, blank=True, default="")`
   - `family`: `CharField(max_length=40, blank=True, default="")`
   - `route`: `CharField(max_length=40, blank=True, default="")`
   - `predicted_chance_pct`: `PositiveSmallIntegerField()`
   - `feature_vector`: `JSONField(default=dict)` — anonymised numeric features (`gpa_margin`, `coursework_ratio`, `language_margin`, `experience_months`, `fit_score`, `winner_similarity`, `base_rate`)
   - `won`: `BooleanField()` — `True` for `ADMITTED` / `ADMITTED_CONDITIONAL`, `False` for `REJECTED`
   - `recorded_at`: `DateTimeField(auto_now=True)`

### 3.2 Tenant-Scoped Copy (`apps/funding/models.py::RecommendationCandidate`)
- Add `estimated_chance_pct = models.PositiveSmallIntegerField(null=True, blank=True)` and `calibration_features = models.JSONField(default=dict, blank=True)` to `RecommendationCandidate` (with check constraint `candidate_estimated_chance_pct_range`: `estimated_chance_pct IS NULL OR (estimated_chance_pct >= 1 AND estimated_chance_pct <= 100)`).
- *Builder call (GDPR erasure):* Register both `estimated_chance_pct` and `calibration_features` in `REDACT["funding.RecommendationCandidate"]` in `apps/audit/redaction.py`, and call `sync_outcome_calibration_records()` during `runtime_engine` erasure/calibration sync so erased students' calibration rows are removed.
- Populated by `apps/research/services.py::_publish` from `PackedApplication.estimated_chance_pct` and `PackedAward.estimated_chance_pct`.
- Read by `apps/dashboard/board.py::build_card` (`Card.chance_line: str`) and `templates/student/_candidate.html` / `templates/student/_card.html` / `templates/student/programme.html` without touching any catalogue table on the web tier.

---

## 4. Cold-Start -> Warm-Start -> ML Probability Calculation (`apps/funding/probability.py`)

### 4.1 Step 1 — Base Rate Prior $p_0 \in [0.02, 0.90]$
- **For a Programme (`estimate_program_admission_chance`):**
  1. If a programme statement or claim states an explicit selection rate or `admitted ÷ applicants` ratio, use that rate.
  2. Otherwise, derive the corridor/regime base rate from `program.country_code` and `CandidateFacts`:
     - Rule-based European public master's (`DE`, `AT`, `BE`, `IT`, `PL`, `HU`, `EE`, `LT`, `LV`, `PT`, `ES`, `FI`, `SE`, `NO`) where the student satisfies all required statements: $p_0 = 0.65$.
     - Capacity-competitive / selective master's (`FR`, `NL`, `GB`, `CH`, `IE`, `DK`, `CZ`, `JP`, `KR`, `SG`, `CA`, `AU`, `NZ`) or joint `CONSORTIUM`/`JOINT` degrees: $p_0 = 0.30$ (`0.18` for Erasmus Mundus / joint consortium programmes).
     - Highly selective US/global research programmes (`US`): $p_0 = 0.20$.
- **For a Scholarship / Award (`estimate_scholarship_chance`):**
  1. If `route == "AUTOMATIC_ON_ADMISSION"`: return `100` (when attached to an admission offer) or the programme's admission chance.
  2. If the opportunity text/claims state an explicit selection rate (e.g., `"1% of applicants"`, `"20 scholarships for 500 applicants"`), parse and use that rate.
  3. Otherwise, derive $p_0$ from `(award.family, award.route, award.tuition, award.living)`:
     - Flagship full-cover national/supranational schemes (`GOVERNMENT`, `SUPRANATIONAL`, `HOME_GOVERNMENT`, full tuition + full living): $p_0 = 0.08$ (`8%`).
     - Selective university-wide or foundation full scholarships (`UNIVERSITY_WIDE`, `PRIVATE_FOUNDATION` with full cover): $p_0 = 0.15$ (`15%`).
     - Departmental or partial fee waivers (`DEPARTMENT_OR_PROGRAM` or partial cover): $p_0 = 0.28$ (`28%`).

### 4.2 Step 2 — Student Profile & Transcript Margin Adjustment (Log-Odds Shift $\Delta_{\text{profile}}$)
Computed from `CandidateFacts` and `evaluate_program_statement`:
- **Academic & Fit Score (`ACADEMIC_FIT` and `PROGRAM_FIT` in `dimension_scores`):**
  - Centered at `75`: $\Delta_{\text{fit}} = \frac{\text{fit\_avg} - 75}{25} \times 0.45$ (in log-odds).
- **Coursework / Transcript Status:**
  - All coursework statements `SATISFIED`: $+0.25$ log-odds.
  - Any coursework statement `BORDERLINE` or `CONDITIONAL_BRIDGE`: $-0.45$ log-odds.
  - Any coursework statement `FAILED`: $-1.10$ log-odds.
- **GPA / Grade Margin (converted to 0–100 scale via `convert_grade_to_bavarian`):**
  - High GPA (Bavarian $\le 1.7$, i.e. top tier): $+0.30$ log-odds.
  - Solid GPA ($1.7 < \text{Bavarian} \le 2.3$): $+0.10$ log-odds.
  - Near cutoff ($2.3 < \text{Bavarian} \le 3.0$): $-0.20$ log-odds.

### 4.3 Step 3 — 3rd-Party LinkedIn Winner Archetype Similarity ($\Delta_{\text{winners}}$)
When a `WinnerCohortProfile` with `sample_size >= 3` exists for the programme or opportunity:
- Compute `similarity` $\in [0.0, 1.0]$ across up to 4 dimensions present in the cohort profile:
  1. **Prior degree field match** (`0.40` weight): share of winners whose `prior_degree_fields` overlap the student's `academic_history` fields (resolved through `resolve_field_taxonomy`).
  2. **Work experience alignment** (`0.25` weight): `1.0` if student's total experience months $\ge \text{p25}$ (or within `[p25, p75]`), `0.5` if within half of `p25`, `0.15` if `p25 >= 12` and student has `0` months.
  3. **Origin country / regional representation** (`0.20` weight): `1.0` if student's `nationality` appears in `origin_country_counts`, `0.5` if neutral/diverse cohort.
  4. **Research signal alignment** (`0.15` weight): if `research_signal_rate >= 0.50`, checks whether student has research interests/thesis/publications.
- Map `similarity` to a bounded log-odds shift $\Delta_{\text{winners}} = (\text{similarity} - 0.50) \times 0.80 \in [-0.40, +0.40]$ (weighted by $\min(1.0, \text{sample\_size} / 15)$).

### 4.4 Step 4 — Warm-Start Empirical Bayes & Calibrated ML Blend
- Convert $\text{logit}(p_{\text{cold}}) = \text{logit}(p_0) + \Delta_{\text{profile}} + \Delta_{\text{winners}}$ back via $\sigma(\cdot)$ to $p_{\text{cold}}$.
- Query `OutcomeCalibrationRecord` counts $(n_{\text{won}}, n_{\text{total}})$ for the exact programme/opportunity (or corridor):
  - **1 to 49 outcomes (Beta-Binomial Empirical Bayes):**
    $$p_{\text{posterior}} = \frac{\alpha_0 + n_{\text{won}}}{\alpha_0 + \beta_0 + n_{\text{total}}}, \quad \alpha_0 = M \cdot p_{\text{cold}}, \; \beta_0 = M \cdot (1 - p_{\text{cold}}), \; M = 15$$
  - **50+ outcomes (Fitted Logistic Calibration over `feature_vector`):**
    Fits/evaluates regularized logistic regression weights over standardized `feature_vector` blended with $p_{\text{posterior}}$.
- Clamp final percentage to `int(round(p * 100))` in `[1, 95]`.

---

## 5. 3rd-Party LinkedIn Winner Scraper (`apps/research/winner_scraper.py`)

- **Provider Protocol (`WinnerSearchProvider`):**
  - `search_winners(query: str, *, program_name: str, holder_name: str, country_code: str, limit: int = 50) -> Sequence[RawWinnerProfile]`
  - Default implementation `HttpThirdPartyLinkedInProvider` reads `LINKEDIN_WINNER_PROVIDER_URL` and `LINKEDIN_WINNER_API_KEY` from `os.environ` / Django settings (supporting Proxycurl / People Data Labs / Bright Data / Exa JSON payloads).
- **Privacy Sanitizer (`aggregate_winner_cohort`):**
  - Accepts `Sequence[RawWinnerProfile]` in memory, immediately discards any `name`, `linkedin_url`, `profile_id`, or free-text bio, and aggregates only:
    - `sample_size`
    - `origin_country_counts` (ISO-2 codes)
    - `prior_degree_fields` (lowercased subject tokens)
    - `prior_degree_levels` (`BACHELOR`, `MASTER`, `DOCTORATE`)
    - `work_experience_months_p25`, `work_experience_months_median`, `work_experience_months_p75`
    - `research_signal_rate`
  - Upserts `WinnerCohortProfile` for the target `Program` or `FundingOpportunity`.
- **Management Command:** `python manage.py sync_winner_cohorts` for Elmify staff / scheduled worker runs.

---

## 6. Access Control & Tenant Isolation (`Elmify Staff` vs. `B2B Customers`)

1. **Database Role Boundary (`runtime_web` vs. `runtime_engine`):**
   - `WinnerCohortProfile` and `OutcomeCalibrationRecord` are catalogue tables alongside `Program` and `FundingOpportunity`.
   - `runtime_web` (the Postgres role used by all web requests) is **never** granted `SELECT` on `Program`, `FundingOpportunity`, `WinnerCohortProfile`, or `OutcomeCalibrationRecord`.
2. **B2B Customer Access (`OWNER` & `COUNSELOR`):**
   - Bound to their `Agency` tenant via `HostTenantContextMiddleware` and Postgres RLS (`app.tenant_id`).
   - `COUNSELOR` views in `apps/dashboard/views.py` enforce `CounselorAssignment(counselor=counselor, student_id=student_id, active=True)`.
   - B2B users see only their own students' boards and the `estimated_chance_pct` copied onto those students' `RecommendationCandidate` rows.
3. **Elmify Staff Access (`PlatformAgency` + `PLATFORM_ADMIN` / `is_staff` + MFA):**
   - All `/platform/*` routes (including `/platform/resolution/`, `/platform/gold/`, and the new `/platform/catalogue/` summary endpoint) enforce `_operator(request)` in `apps/research/views.py`, requiring:
     1. Request host belongs to `PlatformAgency`.
     2. Active `Membership.Role.PLATFORM_ADMIN` (or Django `is_staff` / `is_superuser` on the platform agency).
     3. Verified TOTP MFA (`require_staff_mfa`).
   - Any attempt by a B2B `OWNER`, `COUNSELOR`, or `STUDENT` to access `/platform/*` raises `403 PermissionDenied`.

---

## 7. Card & Page Rendering

- **`templates/student/_candidate.html` (Pack & Recommendation Pool card):**
  - Directly below `<p>Fit: {{ candidate.eligibility_status.label }}</p>`, render:
    ```html
    {% if candidate.estimated_chance_pct %}<p>We estimate that there is an ~{{ candidate.estimated_chance_pct }}% chance</p>{% endif %}
    ```
- **`templates/student/_card.html` (Student & Counsellor Application Board card) & `templates/student/programme.html`:**
  - Carry `chance_line: str = ""` on `apps/dashboard/board.py::Card` (populated from `candidate.estimated_chance_pct` when the application is still undecided: `f"We estimate that there is an ~{candidate.estimated_chance_pct}% chance"`).
  - Render `{% if card.chance_line %}<p>{{ card.chance_line }}</p>{% endif %}` on `templates/student/_card.html` (and on `templates/student/programme.html`).
