# Empirically Calibrated Multi-Reader Dawid-Skene Arbitration, Official Selectivity Priors, and IPW Winner Archetypes

**Date:** 2026-11-19
**Researcher:** Deep Researcher 2 (Argon High Reasoning)
**Scilit Run Provenance:** `/home/orkhan/.scilit/runs/20261119T012334Z-38c5cf38/report.md` (`antigravity/argon`, 234 consulted, 60 scored, 27 accepted)
**Target Modules:**
- `apps/research/programme_scraper/arbitration.py` (lines 1–438)
- `apps/research/programme_scraper/orchestrator.py` (lines 1–195)
- `apps/research/programme_scraper/specs.py` (lines 126–195)
- `apps/research/extraction.py` (lines 130–440)
- `apps/research/catalog.py` (lines 273–699)
- `apps/research/winner_scraper.py` (lines 465–933)
- `apps/funding/probability.py` (lines 1–390, 666–1170)

---

## Executive Summary

1. **Multi-Reader Dawid-Skene Arbitration & Selective Abstention (`apps/research/programme_scraper/`)**:
   - `arbitration.py` implements Proposition 1 cost-sensitive Dawid-Skene log-odds arbitration (`DawidSkeneSlotParams`, `slot_escalation_bounds`, `slot_posterior_log_odds`) [^1] [^2] and selective fail-closed abstention (`status="unresolved"`) aligned with conformal risk control [^3], but currently only covers `tuition` (`tuition_amount`, `tuition_period`) and `conditional_free_tuition` (`tuition_free_all_internationals`) using hardcoded confusion parameters `sensitivities=(0.90, 0.90)` and `specificities=(0.88, 0.88)`.
   - `scrape_fetched_programme_page` (`orchestrator.py:40-95`, called inline by `pipeline.py:639`) runs only Tier-0 deterministic extraction (`extract_tier0_programme_facts`) and drops unresolved/high-risk tuition without calling `refine_with_dual_readers`.
   - **Blueprint:** Extend `ProgrammeQuestionSet` (`specs.py:142-194`) and `needs_high_risk_arbitration` (`arbitration.py:172-235`) to all six high-consequence slots (`tuition`, `application_fee`, `deadline`, `min_gpa`, `ielts_bar`, `scholarship_suspended`), wire optional `screen` and `limit` into `scrape_fetched_programme_page` and `seam_bindings.py:852`, and calibrate per-slot reader sensitivities and specificities $(\hat{\alpha}_{q,k}, \hat{\beta}_{q,k})$ dynamically via Beta-Binomial conjugate shrinkage [^4] over audited `GoldItem` (`apps/research/models.py:1644`) and `DecisionRecord` (`apps/research/models.py:805`) history.

2. **Persisting & Consuming Official Selectivity Priors (`extraction.py` $\rightarrow$ `catalog.py` $\rightarrow$ `probability.py`)**:
   - `ExtractedClaims` (`extraction.py:419-435`) extracts `published_selection_rate` (`SelectionRateClaim`), `awards_per_cycle` (`CountClaim`), `applicants_per_cycle` (`CountClaim`), `published_minimum_grade` (`GradeThresholdClaim`), `selectivity_signals`, and `grade_equivalence_rules` (`GradeEquivalenceRuleClaim`).
   - Currently, `catalog.py::claim_rows` (`catalog.py:273-419`) omits these six fields, so they are discarded when `ExtractedClaims` goes out of scope.
   - **Blueprint:** Emit structured, citation-anchored `OfficialEvidenceClaim` rows in `catalog.py::claim_rows` using existing `OfficialEvidenceClaim.ClaimClass` values (`STRUCTURE`, `FUNDING`, `ELIGIBILITY`) so zero schema migrations are required, parse them into `CandidateFacts` / `AwardCandidateFacts`, and pool them with institutional/regime baselines $p_{\text{reg}}$ in `probability.py` via Beta-Binomial and log-odds Empirical Bayes shrinkage [^4].

3. **Integrating Horvitz-Thompson / Hájek IPW & Empirical Bayes `WinnerArchetype` into `probability.py` (`winner_scraper.py` $\rightarrow$ `probability.py`)**:
   - `winner_scraper.py:611-770` already computes a de-biased `WinnerArchetype` using clipped platform reporting propensities $\pi_i = \max(\pi_{\min}, p_{\text{platform}}(c_i, d_i))$ [^5], stabilized Hájek / Horvitz-Thompson IPW weights $w_i = 1/\pi_i$ [^6], Kish's effective sample size $n_{\text{eff}} = (\sum w_i)^2 / \sum w_i^2$ [^7], and Empirical Bayes shrinkage $\lambda(n_{\text{eff}}) = n_{\text{eff}} / (n_{\text{eff}} + \kappa)$ [^4].
   - However, `_sync_winner_cohort` (`winner_scraper.py:880-898`) only persists the unweighted `aggregate_winner_cohort` dictionary into `WinnerCohortProfile` DB columns and attaches `cohort.archetype = archetype` as an ephemeral in-memory attribute. When `probability.py::_winner_archetype_similarity` (`probability.py:666-740`) reads `WinnerCohortProfile` from PostgreSQL, it uses unweighted counts and raw `sample_size` $n$ instead of $n_{\text{eff}}$, and `_calibrate_with_outcomes_and_se` (`probability.py:771-918`) does not propagate $n_{\text{eff}}$ into `epistemic_se_logit`.
   - **Blueprint:** Persist the serialized `WinnerArchetype` dictionary inside `WinnerCohortProfile.prior_degree_levels["__archetype__"]` (zero-migration compatible) alongside IPW-debiased field/country shares, consume `WinnerArchetype` and Kish's $n_{\text{eff}}$ in `_winner_archetype_similarity` and `is_selective_candidate`, and propagate $n_{\text{eff}}$ into the epistemic logit variance $\operatorname{Var}(\eta)$ in `_calibrate_with_outcomes_and_se`.

---

## Section 1: Empirically Calibrated Multi-Reader Dawid-Skene Arbitration

### 1.1 Mathematical Formulation: Cost-Sensitive Dawid-Skene & Conformal Risk Abstention

Let $Y \in \{0, 1\}$ denote the latent ground-truth indicator for a binary or candidate-selection extraction claim on slot $q$ (e.g., whether candidate amount $m_j$ is the international Master's tuition fee, or whether tuition is unconditionally free for all non-EU students), with slot-specific prior $\pi_q = P(Y = 1) \in (0, 1)$.

Under the Dawid-Skene observer error model [^1] [^2], $K$ conditional-independent Tier-1 cheap readers (`Screen` / `Stack.readers`) emit binary votes $\mathbf{y} = (y_1, \dots, y_K) \in \{0, 1\}^K$ characterized by per-slot, per-reader sensitivity $\alpha_{q,k} = P(y_k = 1 \mid Y = 1)$ and specificity $\beta_{q,k} = P(y_k = 0 \mid Y = 0)$, satisfying the informativeness condition $\alpha_{q,k} > 1 - \beta_{q,k}$.

By Bayes' theorem, the posterior log-odds $L_q(\mathbf{y}) = \ln \frac{P(Y=1 \mid \mathbf{y})}{P(Y=0 \mid \mathbf{y})}$ is additive over the prior and individual reader likelihood ratios (`arbitration.py:113-126`):

$$L_q(\mathbf{y}) = \ln \frac{\pi_q}{1 - \pi_q} + \sum_{k=1}^K \left[ y_k \ln \frac{\alpha_{q,k}}{1 - \beta_{q,k}} + (1 - y_k) \ln \frac{1 - \alpha_{q,k}}{\beta_{q,k}} \right]$$

with posterior probability $p_q(\mathbf{y}) = \sigma(L_q(\mathbf{y})) = (1 + e^{-L_q(\mathbf{y})})^{-1}$.

Let the asymmetric decision loss matrix be:
- $c_{q,\text{fp}} > 0$: loss of accepting a false positive ($\hat{Y} = 1$ when $Y = 0$, e.g. telling a student a programme is tuition-free when it charges EUR 18,000/year),
- $c_{q,\text{fn}} > 0$: loss of a false negative ($\hat{Y} = 0$ when $Y = 1$),
- $c_{q,\text{judge}} \in (0, \min(c_{q,\text{fp}}, c_{q,\text{fn}}))$: marginal cost of escalating to the Tier-2 frontier judge (`active_readers.decider`).

The Bayes-expected loss of the three actions $\mathcal{A} = \{\text{accept } (\hat{Y}=1), \text{reject } (\hat{Y}=0), \text{escalate}\} $ given $\mathbf{y}$ is:
- $R(\hat{Y}=1 \mid \mathbf{y}) = (1 - p_q(\mathbf{y})) c_{q,\text{fp}}$
- $R(\hat{Y}=0 \mid \mathbf{y}) = p_q(\mathbf{y}) c_{q,\text{fn}}$
- $R(\text{escalate} \mid \mathbf{y}) = c_{q,\text{judge}}$ (assuming an oracle or near-zero residual error Tier-2 judge with quote verification)

Equating $R(\hat{Y}=0 \mid \mathbf{y}) = R(\text{escalate} \mid \mathbf{y})$ and $R(\hat{Y}=1 \mid \mathbf{y}) = R(\text{escalate} \mid \mathbf{y})$ yields the exact Bayes-optimal log-posterior-odds escalation interval $(\theta_{q,\text{low}}, \theta_{q,\text{high}})$ (`arbitration.py:102-110`):

$$\theta_{q,\text{low}} = \ln \frac{c_{q,\text{judge}}}{c_{q,\text{fn}} - c_{q,\text{judge}}}, \qquad \theta_{q,\text{high}} = \ln \frac{c_{q,\text{fp}} - c_{q,\text{judge}}}{c_{q,\text{judge}}}$$

Escalation to Tier-2 is Bayes-optimal if and only if $\theta_{q,\text{low}} < L_q(\mathbf{y}) < \theta_{q,\text{high}}$. When Tier-2 is invoked, conformal risk control [^3] requires that if the frontier decider cannot anchor its answer to a verifiable substring quote (`locate(given[0].quote, bundle.section) is None` when `val not in rq.unquoted`), the system must abstain (`status="unresolved"`, `value=None`) so expected financial/eligibility error remains bounded below the target risk threshold.

### 1.2 Extending Arbitration to All Six High-Risk Programme Slots

Currently, `specs.py:142-194` (`ProgrammeQuestionSet.questions`) and `arbitration.py:172-235` (`needs_high_risk_arbitration`) only arbitrate `tuition` and `conditional_free_tuition`. The table below defines the complete six-slot arbitration specification:

| Slot Key (`unresolved_slots` / `high_risk_flags`) | Question ID(s) in `ProgrammeQuestionSet` | Baseline Prior $\pi_q$ | Costs $(c_{\text{fp}}, c_{\text{fn}}, c_{\text{judge}})$ | Escalation Trigger in `needs_high_risk_arbitration` |
|---|---|---|---|---|
| `tuition` (`unresolved_slots`) | `tuition_amount`, `tuition_period` | $0.20$ | $(50.0, 5.0, 1.0)$ | Cheap readers disagree, OR agreed amount triggers `detect_tuition_amount_spread_risk` ($\ge 2\times$ same-currency spread), OR agreed `tuition_period` conflicts with `_period_from_context` |
| `conditional_free_tuition` (`high_risk_flags`) | `tuition_free_all_internationals` | $0.15$ (cond) / $0.80$ (clean) | $(100.0, 5.0, 1.0)$ | Both cheap readers vote `"yes"` while `_CONDITIONAL_GUARD_RE` or EU/non-EU split is present ($L(\mathbf{y}) = 2.546 \in (-1.386, 4.595)$) |
| `application_fee` (`unresolved_slots`) | `application_fee_amount` | $0.25$ | $(40.0, 10.0, 1.0)$ | Multiple candidate fee amounts in `candidates.amounts` or conditional fee waiver guard (`_CONDITIONAL_GUARD_RE`) |
| `deadline` (`unresolved_slots` / `ambiguous_deadline`) | `application_deadline_date` | $0.20$ | $(120.0, 15.0, 1.0)$ | Multiple candidate dates in `candidates.dates` (e.g. EU vs non-EU deadline) where agreed date lacks explicit international/non-EU line context |
| `min_gpa` (`unresolved_slots` / `ambiguous_min_gpa`) | `minimum_gpa_bar` | $0.25$ | $(80.0, 10.0, 1.0)$ | Multiple grade numbers or conflicting scale thresholds where a false-positive high bar closes an eligible route |
| `ielts_bar` (`unresolved_slots` / `ambiguous_ielts_bar`) | `minimum_language_bar` | $0.30$ | $(60.0, 10.0, 1.0)$ | Conflicting CEFR/IELTS/TOEFL levels on the page (e.g. B2 general vs C1 track-specific) |
| `scholarship_suspended` (`high_risk_flags`) | `scholarship_intake_suspended` | $0.15$ | $(80.0, 100.0, 1.0)$ | Any suspension/paused keyword triggers `scholarship_suspended`; both `"yes"` and `"no"` agreements under conditional guards fall inside $(\theta_{\text{low}}, \theta_{\text{high}})$ |

### 1.3 Empirically Calibrated Per-Slot Confusion Priors from `GoldItem` & `DecisionRecord`

Instead of static `sensitivities=(0.90, 0.90)` and `specificities=(0.88, 0.88)`, we derive empirically calibrated posteriors $(\hat{\alpha}_{q,k}, \hat{\beta}_{q,k})$ from the platform's existing audit tables:
1. `GoldItem` (`apps/research/models.py:1644-1704`): holds operator-verified truth labels `verdict in ("correct", "wrong", "not_on_page")` keyed by `(question, page_url, line_sha256)`.
2. `DecisionRecord` (`apps/research/models.py:805-860`): records every reader model's vote (`model`, `question_id`, `decision`, `value`) across extraction runs.

For each slot question $q$ and reader $k \in \{1, 2\}$ with conjugate Beta priors $\alpha_{q,k} \sim \operatorname{Beta}(a_{0,\alpha}, b_{0,\alpha})$ and $\beta_{q,k} \sim \operatorname{Beta}(a_{0,\beta}, b_{0,\beta})$ where $(a_{0,\alpha}, b_{0,\alpha}) = (18.0, 2.0)$ (prior mean $0.90$, concentration $\kappa_0 = 20$) and $(a_{0,\beta}, b_{0,\beta}) = (17.6, 2.4)$ (prior mean $0.88$, concentration $\kappa_0 = 20$), Empirical Bayes posterior shrinkage [^4] gives:

$$\hat{\alpha}_{q,k} = \frac{a_{0,\alpha} + \text{TP}_{q,k}}{a_{0,\alpha} + b_{0,\alpha} + \text{TP}_{q,k} + \text{FN}_{q,k}}, \qquad \hat{\beta}_{q,k} = \frac{a_{0,\beta} + \text{TN}_{q,k}}{a_{0,\beta} + b_{0,\beta} + \text{TN}_{q,k} + \text{FP}_{q,k}}$$

To guarantee the `DawidSkeneSlotParams.__post_init__` invariant $\hat{\alpha}_{q,k} > 1 - \hat{\beta}_{q,k}$, if $\hat{\alpha}_{q,k} + \hat{\beta}_{q,k} \le 1.02$, we project $(\hat{\alpha}_{q,k}, \hat{\beta}_{q,k})$ back toward $(0.90, 0.88)$ via convex combination until $\hat{\alpha}_{q,k} + \hat{\beta}_{q,k} \ge 1.05$.

```python
# Blueprint addition in apps/research/programme_scraper/arbitration.py
@dataclass(frozen=True)
class ReaderAuditCounts:
    tp: int = 0
    fn: int = 0
    tn: int = 0
    fp: int = 0


def calibrate_slot_params(
    base: DawidSkeneSlotParams,
    audit_counts: Sequence[ReaderAuditCounts],
    *,
    prior_strength: float = 20.0,
) -> DawidSkeneSlotParams:
    # Shrink observed reader confusion counts toward base via Beta-Binomial Empirical Bayes.
    if not audit_counts:
        return base
    new_sens: list[float] = []
    new_spec: list[float] = []
    for idx, (alpha_0, beta_0) in enumerate(
        zip(base.sensitivities, base.specificities, strict=True)
    ):
        counts = audit_counts[min(idx, len(audit_counts) - 1)]
        a_sens = alpha_0 * prior_strength + counts.tp
        b_sens = (1.0 - alpha_0) * prior_strength + counts.fn
        hat_alpha = max(0.51, min(0.995, a_sens / (a_sens + b_sens)))

        a_spec = beta_0 * prior_strength + counts.tn
        b_spec = (1.0 - beta_0) * prior_strength + counts.fp
        hat_beta = max(0.51, min(0.995, a_spec / (a_spec + b_spec)))

        if hat_alpha <= 1.0 - hat_beta + 0.02:
            hat_alpha = alpha_0
            hat_beta = beta_0
        new_sens.append(round(hat_alpha, 4))
        new_spec.append(round(hat_beta, 4))
    return replace(base, sensitivities=tuple(new_sens), specificities=tuple(new_spec))
```

### 1.4 Wiring `refine_with_dual_readers` into Live Execution (`orchestrator.py`, `pipeline.py`, `seam_bindings.py`)

1. **`apps/research/programme_scraper/orchestrator.py::scrape_fetched_programme_page` (lines 40–95)**:
   - Add keyword arguments `screen: Screen | None = None`, `limit: Limit | None = None`, `readers: Stack | None = None`, `transport: Transport | None = None`.
   - When `(result.unresolved_slots or result.high_risk_flags) and screen is not None and limit is not None`, invoke `result = refine_with_dual_readers(bundle, result, screen=screen, limit=limit, readers=readers, transport=transport)` before filtering `safe_costs` and calling `persist_programme_scrape`.
2. **`apps/research/seam_bindings.py` (line 852)**:
   - Pass the active tap's `Screen` and `Limit(calls=4)` into `scrape_programme_pages(...)` so Stage-2 programme enrichment runs Tier-1 dual-reader refinement and Tier-2 frontier arbitration whenever Tier-0 flags `unresolved_slots` or `high_risk_flags`.

---

## Section 2: Persisting & Consuming Scraped Official Selectivity Priors

### 2.1 Persisting `ExtractedClaims` Selectivity Fields in `apps/research/catalog.py`

In `apps/research/extraction.py` (lines 419, 429–433), `ExtractedClaims` already extracts:
- `published_selection_rate: SelectionRateClaim | None` (`rate: Decimal`, `cycle_label: str`, `evidence: str`)
- `awards_per_cycle: CountClaim | None` (`value: int`, `cycle_label: str`, `evidence: str`)
- `applicants_per_cycle: CountClaim | None` (`value: int`, `cycle_label: str`, `evidence: str`)
- `published_minimum_grade: GradeThresholdClaim | None` (`minimum: str`, `scale: str`, `evidence: str`)
- `selectivity_signals: tuple[str, ...]`
- `grade_equivalence_rules: tuple[GradeEquivalenceRuleClaim, ...]` (`rule_text: str`, `scope: str`, `evidence: str`)

To persist these in `apps/research/catalog.py::claim_rows` (lines 273–419) **without breaking any schema or `CheckConstraint` on `OfficialEvidenceClaim.ClaimClass`** (`IDENTITY`, `STRUCTURE`, `ELIGIBILITY`, `DEADLINE`, `TUITION`, `FUNDING`), we emit canonical bracketed machine-readable tags inside `claim_rows`:

```python
# Blueprint addition in apps/research/catalog.py::claim_rows (before line 418)
    target_selectivity_class = (
        classes.FUNDING if claims.funding_family is not None else classes.STRUCTURE
    )
    if claims.published_selection_rate is not None:
        sr = claims.published_selection_rate
        rows.append(
            (
                target_selectivity_class,
                f"Published selection rate ({sr.cycle_label}) [{sr.rate}] — {sr.evidence}",
            )
        )
    if claims.awards_per_cycle is not None:
        ac = claims.awards_per_cycle
        rows.append(
            (
                target_selectivity_class,
                f"Awards per cycle ({ac.cycle_label}) [{ac.value}] — {ac.evidence}",
            )
        )
    if claims.applicants_per_cycle is not None:
        apc = claims.applicants_per_cycle
        rows.append(
            (
                target_selectivity_class,
                f"Applicants per cycle ({apc.cycle_label}) [{apc.value}] — {apc.evidence}",
            )
        )
    if claims.published_minimum_grade is not None:
        pmg = claims.published_minimum_grade
        rows.append(
            (
                classes.ELIGIBILITY,
                f"GRADE: Minimum grade {pmg.minimum} ({pmg.scale}) "
                f"[{pmg.minimum} / {pmg.scale}] — {pmg.evidence}",
            )
        )
    for eq_rule in claims.grade_equivalence_rules:
        rows.append(
            (
                classes.ELIGIBILITY,
                f"GRADE_EQUIVALENCE ({eq_rule.scope}): {eq_rule.rule_text} — {eq_rule.evidence}",
            )
        )
    for sig in claims.selectivity_signals:
        if sig.strip():
            rows.append(
                (
                    classes.STRUCTURE,
                    f"Selectivity signal: {sig.strip()}",
                )
            )
```

Because `write_catalog_entry` (`catalog.py:534-566`) links every `(claim_class, text)` row in `rows` to `ProgramEvidenceClaim` and (via `_write_opportunity` at `catalog.py:695-698`) to `FundingOpportunityEvidenceClaim`, both programme and scholarship candidates automatically inherit these `OfficialEvidenceClaim` rows.

### 2.2 Beta-Binomial & Log-Odds Empirical Bayes Pooling in `apps/funding/probability.py`

When `apps/funding/facts.py` builds `CandidateFacts` or `AwardCandidateFacts` from `OfficialEvidenceClaim` rows, a lightweight parser `_extract_official_selectivity_prior(claims_or_conditions, statements)` extracts:
- `published_selection_rate` $r_{\text{pub}} \in (0, 1)$,
- `awards_per_cycle` $K \in \mathbb{Z}_{\ge 0}$,
- `applicants_per_cycle` $N \in \mathbb{Z}_{> 0}$.

Given the institutional/regime or award-family baseline prior $p_{\text{reg}} \in (0.01, 0.95)$ (`probability.py:956-973, 1071-1080`) with prior concentration $\kappa_{\text{reg}} = 15.0$ ($\alpha_{\text{reg}} = \kappa_{\text{reg}} p_{\text{reg}}$, $\beta_{\text{reg}} = \kappa_{\text{reg}}(1 - p_{\text{reg}})$), we pool the official scraped figures with $p_{\text{reg}}$ via Empirical Bayes shrinkage [^4]:

1. **Both `awards_per_cycle` ($K$) and `applicants_per_cycle` ($N$) published ($0 < K \le N$)**:
   To prevent an annual global applicant count ($N = 50{,}000$) from overwhelming student-specific covariates or cycle drift, cap the effective pseudo-sample size of published aggregate counts at $N_{\max} = 85.0$:
   $$N_{\text{eff,pub}} = \min(\text{float}(N), 85.0), \qquad K_{\text{eff,pub}} = N_{\text{eff,pub}} \cdot \frac{K}{N}$$
   $$p_0 = \frac{\alpha_{\text{reg}} + K_{\text{eff,pub}}}{\alpha_{\text{reg}} + \beta_{\text{reg}} + N_{\text{eff,pub}}} = \lambda_{\text{pub}} \left(\frac{K}{N}\right) + (1 - \lambda_{\text{pub}}) p_{\text{reg}}, \qquad \lambda_{\text{pub}} = \frac{N_{\text{eff,pub}}}{N_{\text{eff,pub}} + \kappa_{\text{reg}}}$$

2. **Direct `published_selection_rate` ($r_{\text{pub}}$) published without raw counts**:
   Using effective pseudo-sample weight $N_{\text{eff,rate}} = 45.0$ ($\lambda_{\text{rate}} = \frac{45.0}{45.0 + 15.0} = 0.75$), pool in log-odds space:
   $$\operatorname{logit}(p_0) = \lambda_{\text{rate}} \operatorname{logit}(\operatorname{clip}(r_{\text{pub}}, 0.005, 0.95)) + (1 - \lambda_{\text{rate}}) \operatorname{logit}(p_{\text{reg}})$$

3. **Only `awards_per_cycle` ($K$) published**:
   Using a regime reference denominator $N_{\text{ref}} = 250.0$ and low pseudo-sample weight $N_{\text{eff,quota}} = 10.0$ ($\lambda_{\text{quota}} = 10.0 / 25.0 = 0.40$):
   $$\hat{p}_{\text{quota}} = \operatorname{clip}\left(\frac{K}{N_{\text{ref}}}, 0.01, 0.90\right), \qquad p_0 = \lambda_{\text{quota}} \hat{p}_{\text{quota}} + (1 - \lambda_{\text{quota}}) p_{\text{reg}}$$

4. **Epistemic Prior Concentration Boost ($\Delta\kappa_{\text{pub}}$)**:
   In `_calibrate_with_outcomes_and_se` (`probability.py:784-791`), replace the static `kappa = 10.0` with:
   $$\kappa_{\text{total}} = 10.0 + \Delta\kappa_{\text{pub}}, \qquad \Delta\kappa_{\text{pub}} = \begin{cases} 25.0 & \text{if } (K, N) \text{ published} \\ 15.0 & \text{if } r_{\text{pub}} \text{ published} \\ 5.0 & \text{if only } K \text{ published} \\ 0.0 & \text{otherwise} \end{cases}$$
   This directly reduces the cold-start intercept variance $\frac{1}{\alpha_0 + 0.5} + \frac{1}{\beta_0 + 0.5}$ when an official selection rate is cited.

---

## Section 3: Integrating Horvitz-Thompson / Hájek IPW & Empirical Bayes `WinnerArchetype` into `probability.py`

### 3.1 Statistical Theory: Platform Propensity IPW, Hájek Stabilization & Kish Effective Sample Size

LinkedIn winner cohorts scraped by `apps/research/winner_scraper.py` suffer from severe non-random platform self-reporting bias: winners from high-penetration countries (e.g. `US: 0.85`, `NL: 0.82`) and tech/business fields (`0.92`) appear on LinkedIn at up to $15\times$ the rate of winners from lower-penetration countries (`CN: 0.12`, `JP: 0.15`, `UZ: 0.18`) or humanities/agriculture fields (`0.48`).

For each matched profile $i \in \{1, \dots, n\}$, `platform_reporting_propensity` (`winner_scraper.py:546-583`) computes the clipped inclusion propensity [^5]:

$$\pi_i = \max\left(\pi_{\min}, \min(1.0, p_{\text{country}}(c_i) \cdot p_{\text{field}}(d_i) \cdot p_{\text{level}}(l_i))\right), \qquad \pi_{\min} = 0.05$$

With inverse-propensity weights $w_i = 1 / \pi_i$, the Horvitz-Thompson estimator [^6] of a cohort attribute $Z_i$ is $\hat{\mu}_{\text{HT}} = N^{-1} \sum_{i=1}^n w_i Z_i$, and its variance-stabilized Hájek ratio estimator (`winner_scraper.py:662-751`) is:

$$\hat{\mu}_{\text{Hájek}} = \frac{\sum_{i=1}^n w_i Z_i}{\sum_{i=1}^n w_i}$$

Because unequal weights inflate sampling variance by the design effect $D_{\text{eff}} = 1 + \operatorname{CV}^2(w)$, the true information content of the weighted cohort is governed by Kish's effective sample size (`winner_scraper.py:585-600`) [^7]:

$$n_{\text{eff}} = \frac{\left(\sum_{i=1}^n w_i\right)^2}{\sum_{i=1}^n w_i^2} \in (0, n]$$

and Empirical Bayes shrinkage (`winner_scraper.py:602-609`) [^4] pulls the noisy Hájek mean toward the prior $\mu_0$ with shrinkage factor:

$$\lambda(n_{\text{eff}}) = \frac{n_{\text{eff}}}{n_{\text{eff}} + \kappa}, \qquad \hat{\mu}_{\text{EB}} = \lambda(n_{\text{eff}}) \hat{\mu}_{\text{Hájek}} + (1 - \lambda(n_{\text{eff}})) \mu_0$$

### 3.2 Fixing the Persistence Gap Between `winner_scraper.py` and `WinnerCohortProfile`

In `winner_scraper.py:880-898`, `_sync_winner_cohort` currently writes `**agg` (from `aggregate_winner_cohort`, which uses unweighted `Counter` tallies) to `WinnerCohortProfile` and sets `cohort.archetype = archetype` only in memory.

To persist `WinnerArchetype` without requiring a schema migration on `WinnerCohortProfile` (`apps/research/models.py:1706-1763`):
1. Store the serialized `WinnerArchetype` metadata under a reserved key `"__archetype__"` inside `WinnerCohortProfile.prior_degree_levels` (which is a `models.JSONField(default=dict, blank=True)`), or read `getattr(cohort, "archetype", None)` first and fall back to deserializing `cohort.prior_degree_levels.get("__archetype__")`.
2. Specifically, in `winner_scraper.py::aggregate_winner_cohort`:
   - Embed `"__archetype__"` in `prior_degree_levels` containing:
     `effective_sample_size`, `shrinkage_factor`, `avg_gpa`, `eb_avg_gpa`, `avg_work_months`, `eb_avg_work_months`, `research_share`, `eb_research_share`, `top_prior_universities`, `prior_university_shares`, `origin_country_shares`, `prior_degree_level_shares`, and `prior_degree_field_shares`.

### 3.3 Consuming `WinnerArchetype` in `probability.py` (Point Estimate & Epistemic Logit SE)

1. **Extracting `WinnerArchetype` in `apps/funding/probability.py`**:
   Add helper `_cohort_archetype_meta(cohort: WinnerCohortProfile | None) -> Mapping[str, Any]` that reads `getattr(cohort, "archetype", None)` if present, or `cohort.prior_degree_levels.get("__archetype__", {})` if stored in JSON, falling back cleanly to unweighted counts when absent.

2. **De-biased `_winner_archetype_similarity(profile, cohort)` (`probability.py:666-740`)**:
   - **Field share ($w = 0.40$)**: Use Hájek IPW `prior_degree_field_shares[cf]` instead of raw `cnt / cohort.sample_size`.
   - **Origin country share ($w = 0.20$)**: Use Hájek IPW `origin_country_shares[profile.nationality]` instead of `nat_count / cohort.sample_size`.
   - **Prior university & GPA alignment ($w = 0.10$, when `prior_university_shares` or `eb_avg_gpa` is available)**: Reward prior-institution match or student GPA $\ge \text{eb\_avg\_gpa}$.
   - **Work experience alignment ($w = 0.15$)**: Compare student work months against `eb_avg_work_months` (or `work_experience_months_median`).
   - **Research signal alignment ($w = 0.15$)**: Compare student research signal against Empirical-Bayes `eb_research_share` (fallback `research_signal_rate`).
   - **Kish Effective Sample Size Shrinkage**:
     Replace raw $n_{\text{cohort}} = \text{float}(cohort.sample\_size)$ (`probability.py:736-737`) with Kish's effective sample size $n_{\text{eff}}$ [^7]:
     $$\tau(n_{\text{eff}}) = \frac{n_{\text{eff}}}{n_{\text{eff}} + \kappa_{\text{cohort}}}, \qquad \text{winner\_similarity} = \operatorname{round}\left(\operatorname{clip}\left(\frac{\text{score}}{\text{total\_weight}}, -1.0, 1.0\right) \cdot \tau(n_{\text{eff}}), 4\right)$$

3. **Propagating $n_{\text{eff}}$ into Epistemic Logit Standard Error (`epistemic_se_logit` $\rightarrow$ `ci_low_pct..ci_high_pct`)**:
   - Pass `cohort_n_eff: float = 0.0` (and `prior_kappa_boost: float = 0.0`) into `_calibrate_with_outcomes_and_se` (`probability.py:771-918`) and record `"cohort_n_eff": round(n_eff, 4)` in `features` (or pass via keyword argument so `_FEATURE_KEYS` contract stays unchanged).
   - In `_calibrate_with_outcomes_and_se`:
     - Set $\kappa = 10.0 + \Delta\kappa_{\text{pub}}$.
     - Include the finite-sample IPW variance contribution of `winner_similarity` ($x_{\text{sim}}$) and the structural uncertainty reduction from $n_{\text{eff}}$:
       $$\sigma_{\text{struct}}^2(W_{\text{cal}}, n_{\text{eff}}) = \frac{0.08}{1.0 + 0.10 (W_{\text{exact}} + W_{\text{pool}}) + 0.04 n_{\text{eff}}} + \beta_{\text{sim}}^2 \frac{\tau(n_{\text{eff}})^2 (1 - x_{\text{sim}}^2)}{\max(1.0, n_{\text{eff}} + 1.0)} \cdot \mathbb{I}[n_{\text{eff}} > 0]$$
     - In Phase 3 (`exact_count >= 50`, line 904), initialize the Fisher information diagonal for `"winner_similarity"` as `25.0 + 0.5 * n_eff + l2 * max(1.0, weighted_n)` so high-$n_{\text{eff}}$ cohorts tighten the posterior slope variance on `winner_similarity`.

---

## Sources

[^1]: https://arxiv.org/abs/1803.04924 "A wide range of theoretical and algorithmic contributions are based on the model of Dawid and Skene"
[^2]: https://arxiv.org/abs/1803.02781 "Fast Dawid-Skene: A Fast Vote Aggregation Scheme for Sentiment Classification"
[^3]: https://arxiv.org/abs/2208.02814 "we extend conformal prediction to control the expected value of any monotone loss function"
[^4]: https://arxiv.org/abs/1605.07787 "Flexible signal denoising via flexible empirical Bayes shrinkage"
[^5]: https://arxiv.org/abs/1601.05890 "Covariate balancing propensity score by tailored loss functions"
[^6]: https://arxiv.org/abs/2001.02719 "A note on Horvitz-Thompson estimators for rare subgroup analysis in the presence of interference"
[^7]: https://arxiv.org/abs/1602.03572 "Effective Sample Size for Importance Sampling based on discrepancy measures"
