# Portfolio theory

What the literature proves about choosing applications under a budget, and what that changes in the portfolio design. [src: 2026-08-27-portfolio-theory-synthesis.md]

## What is proven
- Chade & Smith (Econometrica 2006): the Marginal Improvement Algorithm is exactly optimal in O(N²), but only under independence, identical costs, a single kept prize and known calibrated probabilities. [src: 2026-08-27-portfolio-theory-synthesis.md §1]
- Under independence the optimum is upward-diversified with no safety option (the "No Safety Schools Theorem"). [src: 2026-08-27-portfolio-theory-synthesis.md §1]
- With per-option costs the problem is a knapsack, NP-complete, and greedy has no guarantee; Kapur & Hong (2022) give an exact pseudo-polynomial DP and an FPTAS. [src: 2026-08-27-portfolio-theory-synthesis.md §1]
- With correlation, Ali & Shorrer (AER 2025) prove the optimal portfolio contains both a reach and a safety, and it is not greedy. [src: 2026-08-27-portfolio-theory-synthesis.md §1]
- Precedence ("hold offer X before claiming Y") is unsolved; no numeric reach/target/safety ratio has empirical support. [src: 2026-08-27-portfolio-theory-synthesis.md §1]

## The disagreement
- Run 1 found no robust version of this problem; run 2 pointed to robust submodular maximization. The adopted position: run 1 is the authority on what is proven, run 2's citations are leads to verify. [src: 2026-08-27-portfolio-theory-synthesis.md §2]

## Design consequences
- tehsil is in the correlated regime, so the floor is what the optimum looks like, not a guardrail; do not use greedy; solve exactly with a DP over the budget because N is tens of candidates. [src: 2026-08-27-portfolio-theory-synthesis.md §3]
- Delete the `floor(paid_slots / 3)` reach cap; a near-certain outside option truncates the portfolio and pushes budget to reaches. [src: 2026-08-27-portfolio-theory-synthesis.md §3]
- Bands are probability intervals optimised in the worst case, a documented heuristic rather than a proven optimum; for precedence, enumerate staging patterns. [src: 2026-08-27-portfolio-theory-synthesis.md §3]
- Before implementing: check Kapur & Hong's `OptimalApplication.jl` and verify run 2's citations. [src: 2026-08-27-portfolio-theory-synthesis.md §4]

Related: [synthesis cross-check](synthesis-crosscheck.md) adds the behavioural evidence this synthesis lacks [src: 2026-08-29-synthesis-crosscheck.md §6], and [Chevening](../schemes/chevening.md) is the precedence example. [src: 2026-08-27-portfolio-theory-synthesis.md §3]

Superseded: the exact dynamic program is deferred until a probability model exists, and allocation is rule-based meanwhile — see [Tailored programme finding](../../superpowers/specs/2026-09-25-tailored-programme-finding-design.md).
