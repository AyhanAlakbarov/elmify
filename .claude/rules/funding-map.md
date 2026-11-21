---
paths:
  - "apps/funding/**"
  - "tests/funding/**"
---

## Funding area map: the catalogue and a student's pack

<!-- A map, not rules: it says where to look so a session or subagent does not rediscover the layout by grep.
Checked against master e5258ea2 (2026-10-24). When a file named here moves or is renamed, fix its line. -->

This app holds the shared catalogue's tables and the per-student path from catalogue to pack. Finding and reading
sources is `apps/research/` (`research-map.md`). The whole flow, with measurements:
`docs/superpowers/2026-10-24-search-engine-how-it-works.md` §7 (pack) and §1C (programmes).

Big files (over 900 lines): `transcript_eligibility.py` (3,636), `models.py` (2,190), `probability.py` (1,443),
`eligibility.py` (1,228), `pack.py` (1,014), `evaluation.py` (976). Outline first with `grep -n "^def \|^class "`.

**Catalogue to pack**, in order (called from `apps/research/spine.py::build_student_pack`):
1. Pool: `pool.py::candidate_pool`: programmes and served awards a student is evaluated against.
2. Facts: `facts.py`: catalogue rows → facts; what the catalogue does not say, the facts do not say.
3. Gates, transcript rules, and probabilities: `evaluation.py::evaluate` (ten hard gates, dimension scores, `funding_gap`).
   Award & course conditions: `conditions.py`, `eligibility.py`, `transcript_eligibility.py` (7 course/credit/GPA/language/test/work/recency domains), `deadline_conditions.py`, `regions.py`.
   Admission & funded probabilities: `probability.py` (priors, margins, `WinnerCohortProfile` similarity, Empirical Bayes / logistic calibration over `OutcomeCalibrationRecord`; command `sync_outcome_calibration`).
4. Money: `affordability.py`, `fx.py`, rates `rates.py` / `rate_sources.py` (command `fetch_cbar_rates`).
5. Pack: `pack.py::build_pack` (ranking, risk tiers, application budget), grouped for the dashboard in `grouping.py`.
6. Publish and edits: `services.py` (`auto_publish_pack`, `reject_candidate`, `replace_candidate`, `consider_named_program`, `resolve_named_program`).
Is this year's money there: `validity.py`, `cycle_evidence.py`, `cycle_schedule.py` (the reading side is `apps/research/cycle_verification.py`).
What a programme requires: `requirements.py`, `cv_ruleset_scope_map.py`, `letter_prompt_fixtures.py`. The award card's fields: `card.py`. Student-facing text: `explanations.py`; views `views.py`.

Models (`models.py`). Catalogue: `Institution`, `Program`, `ProgramStatement`, `ApplicationPrompt`, `FundingOpportunity`, `FundingBenefit`, `CostComponent`,
`BenefitRule`, `OfficialSource`, `OfficialSourceSnapshot`, the `*EvidenceClaim` tables, `FundingCycleVerification`, `OutcomeCalibrationRecord`.
Per student: `RecommendationRun`, `RecommendationCandidate`, `PackVersion`, `PackCandidate`, `StudentDecision`, `ExchangeRate`.
Tests: `tests/funding/`, usually `test_<module>*.py`; `test_spine.py` runs one student through pool → pack end to end.
