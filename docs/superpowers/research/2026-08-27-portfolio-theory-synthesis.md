# Application-portfolio theory — synthesis and design consequences

**Date:** 2026-08-27. **Inputs:** two independent deep-research runs of the same prompt,
filed as `2026-08-27-portfolio-theory-review-1.md` (the more disciplined of the two) and
`2026-08-27-portfolio-theory-review-2.md`. This document records what they agree on, where
they conflict, and what each finding changes in the portfolio design.

**The prompt asked:** does an established formulation exist for choosing which programmes and
scholarships to apply to under a budget, maximizing the expected value of the best offer
received; is a greedy algorithm provably correct; and does the theory require calibrated
per-student probabilities we do not have.

---

## 1. What both runs agree on

1. **Chade & Smith, "Simultaneous Search" (Econometrica 74(5), 2006) is the canonical result,
   and it is proven, not conjectured.** The Marginal Improvement Algorithm — take the best
   singleton, then repeatedly add the option with the largest marginal gain, stop when the gain
   falls below the incremental cost — returns the exact optimum in O(N²).
2. **It is proven under four conditions, all of which we violate or lack:** independence of
   outcomes across options; identical costs across options (or a cost schedule in the *count* of
   applications, not per-option fees); a single kept prize per option; and known, calibrated
   cardinal probabilities and utilities.
3. **The "No Safety Schools Theorem."** Under independence the optimal portfolio is *upward*
   diversified and contains no safety option — students should gamble up. This is a theorem, and
   it is the opposite of counselling folklore.
4. **Heterogeneous per-option costs break it.** With a real money budget the problem is a
   knapsack and is NP-complete; optimal portfolios stop being nested and greedy carries no
   performance guarantee (Kapur & Hong, "The College Application Problem", arXiv:2205.01869,
   2022). They give an exact pseudo-polynomial DP and an FPTAS.
5. **Correlation breaks it, and correlation is what rationalises safeties.** Ali & Shorrer,
   "Hedging When Applying: Simultaneous Search with Correlation" (AER 115(2), 2025) model a
   common latent score that every school evaluates against its own threshold. Theorem 1: whenever
   the applicant applies to more than one school, **the optimal portfolio contains both a reach
   and a safety**. Their algorithm is polynomial but explicitly *not* greedy, because optimal
   portfolios are not nested under correlation.
6. **Precedence — "you must hold an offer from X before you can claim Y" — is unsolved.** Neither
   run found a portfolio result under precedence constraints. Simultaneous search assumes no
   ordering; sequential search (Weitzman 1979) assumes free recall and no prerequisites.
7. **No numeric reach/target/safety ratio has empirical support.** Ratios like "2/4/2" are
   counselling folklore. The credible empirical work (Hoxby & Avery 2013; Pallais 2015; Ajayi
   2024) documents application *behaviour* and its sensitivity to cost, never the optimality of a
   mix.
8. **Cardinal utilities are assumed as primitives everywhere.** No paper in this literature
   elicits them.

## 2. Where the two runs conflict

**On whether the uncalibrated-probability case is solved.**

- Run 1: no robust, ordinal or distributionally-robust version of *this* problem exists; a
  targeted search found none; this is a genuine gap. Only a *local* stability follows from the
  MIA being defined by strict inequalities — small mis-estimates do not flip a strictly optimal
  set.
- Run 2: the case is addressed by robust submodular maximization — deletion-robust
  (Orlin, Schulz & Udwani 2018) and distributionally robust (Staib et al. 2019) — and one can
  simply run a robust greedy against the lower bound of each coarse probability band.

**Resolution adopted here.** Both are partly right, and the distinction matters. There is no
robust version of the *college-application* problem specifically — Run 1 is correct, and its
verification discipline is better. But the objective is monotone submodular, which both runs
agree on, so the generic robust and distributionally-robust submodular machinery does apply, with
worst-case constant-factor guarantees rather than exactness. Run 2 overstates the fit:
deletion-robustness models an adversary removing chosen elements, which is not the same
uncertainty as "our probability estimate is a coarse interval". Run 2 also carries unrendered
image placeholders and at least two citations that could not be attributed precisely.

**Practical position:** treat Run 1 as the authority on what is proven; treat Run 2's robust
submodular citations as leads worth verifying before we rely on them.

## 3. What this changes in our design

| # | Decision | Basis |
|---|---|---|
| 1 | **We are in the correlated regime, not the independent one.** One DAAD committee spans many programmes; one visa authority spans a destination; one home-country instrument spans its whole approved list. | §1.5 |
| 2 | **The floor is not a paternalistic constraint — it is what the optimum looks like.** Ali & Shorrer prove the optimal portfolio contains both a reach and a safety *because* outcomes are correlated. We should stop describing the floor as a guardrail bolted onto an optimizer and describe it as a property the optimizer must reproduce. | §1.5 |
| 3 | **Do not use greedy.** Our fees are heterogeneous (€0–€150, plus deposits) *and* our outcomes are correlated. Either one alone removes the guarantee. | §1.4, §1.5 |
| 4 | **Solve it exactly with a DP over the budget instead.** The NP-completeness result is asymptotic; our N is tens of candidates per student, not thousands. At that size the exact pseudo-polynomial DP is tractable and we need no approximation at all. This is the single most useful practical consequence: the theory's negative results push us away from greedy and toward exact DP, not toward heuristics. | §1.4 |
| 5 | **Delete the `floor(paid_slots / 3)` reach cap.** No fixed ratio has support. The mix must be derived from the objective, the correlation structure and the outside option. | §1.7 |
| 6 | **A near-certain outside option is a truncator, and it is the mechanism behind "a strong student should reach more".** Enter the guaranteed option (e.g. a home-country scholarship the student will almost certainly win) as a zero-cost element of the portfolio. The downward-recursive value formula then automatically zeroes the marginal value of every option below it and pushes the remaining budget upward into reaches. No conditional branching is needed. | Run 2 §"Algorithmic Mechanics of the Outside Option"; Run 1 §3, citing Ali & Shorrer's risk-loving effect as a proven comparative static |
| 7 | **Bands are probability *intervals*, and we optimise the worst case within them.** We do not need calibrated point estimates; we need intervals that are *correct*. Implement as an explicit sweep across each band's interval, preferring portfolios that stay optimal or near-optimal across it. This must be labelled in the spec as a documented heuristic filling a known gap in the literature — not as a proven optimum. | §2 |
| 8 | **Admission-then-funding collapses cleanly when the funder is distinct.** If the student always accepts funding when offered, the option's value is one compound expectation: `p_admit × [p_fund·u_funded + (1 − p_fund)·u_unfunded]`. That keeps `AUTOMATIC_ON_ADMISSION` and `CONSIDERED_WITH_ADMISSION` inside the tractable framework. A funder shared across programmes re-introduces correlation. | Run 1 §2(C), Run 2 §"Sequential and Nested Decisions" |
| 9 | **Precedence (Chevening's "hold an offer by 8 July") has no result to borrow.** With small N, enumerate the small number of staging patterns rather than seeking a general algorithm. | §1.6 |
| 10 | **We already have the cardinal utility the literature says is hardest to obtain.** `StudentProfileSnapshot.weights` over the evaluation dimensions, scored in `evaluation.py`, is exactly the `u_i` these models assume as a primitive. Both runs flag elicitation as the practical obstacle; we solved it upstream, for a different reason. | §1.8 |

## 4. Worth doing before implementation

- Check Kapur & Hong's `OptimalApplication.jl`, which implements the exact DP and the FPTAS, to
  avoid re-deriving the recursion.
- Verify Run 2's robust-submodular citations (Orlin–Schulz–Udwani 2018; Staib et al. 2019) against
  the actual papers before citing them in the spec.
- Run 1 advises a forward-citation sweep of Chade & Smith (2006) and Kapur & Hong (2022) before
  treating the "no robust version exists" and "no precedence result exists" gaps as definitive.
