# Simultaneous Application Portfolio Optimization under Fee Budget & Correlated Funder Risk

**Date:** 2026-11-03  
**Target Module:** [`apps/funding/pack.py`](file:///home/orkhan/Desktop/tehsil_agent/apps/funding/pack.py) (with upstream probability inputs from [`apps/funding/probability.py`](file:///home/orkhan/Desktop/tehsil_agent/apps/funding/probability.py) and [`apps/research/spine.py`](file:///home/orkhan/Desktop/tehsil_agent/apps/research/spine.py))  
**Scilit Provenance:**
- **`scilit find` Run ID:** `20261103T141638Z-d4f2a14f` (`/home/orkhan/.scilit/runs/20261103T141638Z-d4f2a14f/report.md`, `report.json` — 198 papers consulted, 60 scored, 9 accepted)
- **`scilit ask` Run ID:** `20261103T141909Z-bc9a0289` (`/home/orkhan/.scilit/runs/20261103T141909Z-bc9a0289/report.md`, `report.json` — 11 papers read, 9 PDFs acquired & verified, claim IDs `pqac-0001` through `pqac-0012`)
- **`scilit prove` Verification Runs:**
  - **Proposition 1 (Monotonicity & Submodularity of Common-Shock Portfolio Utility & Success Probability):** `proved: true, fuzz_verified: true (50/50 instances), sympy_verified: true` (86.14s)
  - **Proposition 2 (Strict Overestimation of Portfolio Success by Naive Independence under Shared External Funder):** `proved: true, fuzz_verified: true (50/50 instances), sympy_verified: true` (80.94s)
  - **Proposition 3 (Multi-Funder Common-Shock Failure Probability, Marginal Gain $\Delta P_{\text{success}}(j \mid S)$, & Funder Concentration Ceiling $P_{\text{success}}(S_k) < q_k$):** `proved: true, fuzz_verified: true (50/50 instances across 3 subgoals), sympy_verified: true` (115.75s)

---

## 1. Executive Summary & Primary Literature Ledger

### 1.1 Problem Statement
In [`apps/funding/pack.py`](file:///home/orkhan/Desktop/tehsil_agent/apps/funding/pack.py), `build_pack` constructs a student's actionable application portfolio (`fee_free`, `paid`, `fee_not_known`) subject to:
1. A hard application fee budget $B_{\text{eff}} = \lfloor \text{application\_fee\_budget\_eur} / (1 + \text{BANK\_MARGIN}) \rfloor$ (`BANK_MARGIN = 0.02`, lines 98, 709–713),
2. A total active portfolio cardinality cap $K = \text{MAX\_ACTIVE\_PROGRAMS} = 10$ (line 104), and
3. A partition matroid institution cap $M_{\text{inst}} = \text{MAX\_PER\_INSTITUTION} = 2$ (line 101).

Currently, `rank_candidates` (lines 291–370) scores each programme $i$ in **1D isolation** using a linear combination of its standalone effective chance (`_effective_chance_for`, lines 178–198), route/deadline/scholarship bonuses, and friction penalties (`effective_score`, lines 331–354). Then `build_pack` (lines 784–960) iterates through `ranked` in a **single static 1D pass**, greedily admitting each paid candidate until the remaining fee budget or capacity runs out (with only a brittle 1-step lookahead `_should_reserve_budget_for_anchor`, lines 472–560, that turns off permanently as soon as *any* single `TARGET` or `SAFETY` programme enters the pack, even a fee-free one).

This 1D architecture violates two foundational theorems of simultaneous portfolio search:
1. **Fee-Budget Knapsack Submodularity Failure:** Because a student can enroll in at most one programme (or seeks at least one funded admission), portfolio value is a **monotone submodular set function** $U(S) = \mathbb{E}[\max_{i \in S} Z_i v_i]$, not a modular sum $\sum_{i \in S} p_i v_i$. Under heterogeneous application fees $\sum_{i \in S} c_i \le B_{\text{eff}}$, static 1D ordering by standalone score ignores fee density ($\Delta U / c_i$), allowing one expensive $90\text{ EUR}$ application to crowd out two $45\text{ EUR}$ applications whose combined success probability ($1 - (1-0.40)^2 = 64\%$) and expected utility strictly dominate the single $90\text{ EUR}$ bet ($40\%$). Conversely, pure cost-scaled greedy ($\Delta U / c_i$) without comparing against the unscaled/anchor pass falls into **Example 3 of Kapur & Hong (2022)**, where a cheap $1\text{ EUR}$ safety programme blocks a $500\text{ EUR}$ flagship programme and yields an arbitrarily bad approximation ratio.
2. **Correlated External Funder Risk (Common-Shock Failure):** When a mandatory-funding student applies to multiple programmes $i \in S_k$ whose affordability depends on the **same external scholarship** $k$ (e.g., `HOLDER` / `COUNTRY` / `GLOBAL` schemes such as *Stipendium Hungaricum*, *DAAD*, *Chevening*, *Fulbright*, or the Azerbaijan *Post-Admission Government Scholarship* DP 2022–2028), `compute_funded_admission_probability` ([`apps/funding/probability.py`](file:///home/orkhan/Desktop/tehsil_agent/apps/funding/probability.py#L1422-L1570)) returns the product $p_i = a_i q_k$ as a standalone scalar. Treating $p_i$ as independent across $i \in S_k$ assumes the student gets a fresh, independent draw of scholarship $k$ for every programme applied to. In reality, external scholarship $k$ is a **common shock** $F_k \sim \text{Bernoulli}(q_k)$: if the student is not awarded scholarship $k$ (probability $1 - q_k$), **all** programmes in $S_k$ fail simultaneously. Naive independence strictly overestimates portfolio success probability for $|S_k| \ge 2$ and fails to penalize funder concentration, crowding the pack with positively correlated lottery tickets tied to a single funder ceiling $P_{\text{success}}(S_k) < q_k$.

### 1.2 Primary Literature Ledger (`scilit` Verified)

| Citation | DOI / Identifier | Primary Contribution & Exact Theorems Used | `scilit` Claim IDs |
| :--- | :--- | :--- | :--- |
| **Chade & Smith (2006)**, *"Simultaneous Search"*, *Econometrica* 74(5):1293–1307 | `doi:10.1111/j.1468-0262.2006.00705.x` | Formulates simultaneous application portfolio selection with success probabilities $\alpha_i$, utilities $u_i$, and upward-sloping convex cost $c(|S|)$. Proves $f(S) = \mathbb{E}[\max_{i \in S} Z_i u_i]$ is monotone submodular and that under homogeneous costs, optimal portfolios are nested ($S_1^* \subset S_2^* \subset \dots \subset S_K^*$) and the **Marginal Improvement Algorithm (MIA)** is **exact** (**Theorem 1**). | `pqac-0001`, `pqac-0002`, `pqac-0004` |
| **Kapur & Hong (2022)**, *"The College Application Problem"*, arXiv:2205.01869 | `doi:10.48550/arxiv.2205.01869` | Proves explicit polynomial expansion (**Proposition 1**), the **Variable-Elimination Transformation** (**Lemma 2, Eq. 7**), submodularity (**Theorem 1**), $(1/h)$-inapproximability of the 1D Naïve Algorithm (**Theorem 2 & Example 2**), $O(hm)$ exactness of greedy MIA under unit costs (**Theorems 3–4, Algorithm 1**), discrete concavity in portfolio size (**Theorem 5**), and NP-completeness + failure of nestedness + unbounded failure of pure cost-scaled greedy under heterogeneous application fees $\sum_{j \in X} g_j \le H$ (**Theorem 6 & Example 3**). | `pqac-0001`, `pqac-0003`, `pqac-0004`, `pqac-0005` |
| **Khuller, Moss, & Naor (1999)**, *"The budgeted maximum coverage problem"*, *Information Processing Letters* 70(1):39–45 | `doi:10.1016/S0020-0190(99)00031-9` | Proves that for budgeted coverage / submodular maximization under knapsack budget $B$, taking the maximum of the best single feasible element (or unscaled greedy pass) and the cost-density greedy pass $\Delta f(i \mid S)/c_i$ achieves a $\frac{1}{2}(1 - 1/e) \approx 0.316$ worst-case guarantee, and $(1 - 1/e) \approx 0.632$ with size-3 seed enumeration. | `pqac-0006`, `pqac-0007` |
| **Sviridenko (2004)**, *"A note on maximizing a submodular set function subject to a knapsack constraint"*, *Operations Research Letters* 32(1):41–43 | `doi:10.1016/s0167-6377(03)00062-2` | Extends Khuller-Moss-Naor (1999) from coverage functions to arbitrary non-decreasing submodular functions $f(S)$ subject to knapsack constraint $\sum_{i \in S} c_i \le B$, proving the tight $(1 - 1/e)$ guarantee. | `pqac-0006`, `pqac-0007` |
| **Nutov & Shoham (2020)**, *"Practical Budgeted Submodular Maximization"*, arXiv:2007.04937 | `doi:10.48550/arxiv.2007.04937` | Analyzes practical twin-pass / single-seed budgeted submodular maximization without $O(n^4)$ enumeration, proving improved approximation ratios ($0.43 \approx 0.68(1 - 1/e)$) when comparing unscaled anchor candidates against cost-density greedy passes. | `pqac-0007` |
| **Sarpatwar, Schieber, & Shachnai (2018)**, *"Constrained submodular maximization via greedy local search"*, *Operations Research Letters* | `doi:10.1016/j.orl.2018.11.002` | Combines knapsack budget constraints $\sum_{e \in S} c(e) \le B$ with $k$-system / matroid intersection constraints (such as total cardinality $K = 10$ and partition matroid $M_{\text{inst}} = 2$ per institution) via greedy density with swap/anchor backup (**Algorithm 1 & Theorem 1**). | `pqac-0008` |
| **Ali & Shorrer (2023 / 2025)**, *"Hedging When Applying: Simultaneous Search with Correlation"*, *American Economic Review* 115(1) | `doi:10.1257/aer.20211137` | Proves that when admissions/funding outcomes across options share a common random factor (positively correlated shocks), joint failures are much more likely than under independence. Optimal portfolios **hedge** against the common shock by diversifying into options that do not depend on the same shock (**Proposition 1 & Theorem 1**). | `pqac-0009`, `pqac-0010` |
| **Shorrer (2019)**, *"Simultaneous Search: Beyond Independent Successes"*, *EC '19* | `doi:10.1145/3328526.3329599` | Extends Chade-Smith simultaneous search to correlated admission/funding indicator distributions, proving when downward hedging and diversification across weakly correlated tiers dominate concentration. | `pqac-0009`, `pqac-0010` |
| **Kleinberg, Oren, Ryu, & Tardos (2024)**, *"Modeling Randomness in Matching Markets"*, arXiv:2403.04616 | `doi:10.48550/arxiv.2403.04616` | Contrasts independent vs common-shock (correlated) application success models under limited application budgets, showing that common-shock correlation strictly reduces marginal value of applying to multiple options exposed to the same shock. | `pqac-0010` |
| **Arunachaleswaran, Kannan, & Vohra (2026)**, *"College Applications with Non-Homogeneous Application Costs"*, *ACM TEAC* | `doi:10.1145/3795138` | Analyzes non-homogeneous application costs $c_i$ under budget $B$, showing that cost-aware submodular optimization strictly dominates static 1D preference/chance ordering. | `pqac-0005`, `pqac-0011` |

---

## 2. Formal Mathematical Framework & SymPy-Verified Proofs

### 2.1 Simultaneous Search & Kapur-Hong Variable-Elimination Recurrence
Let $U = \{1, 2, \dots, m\}$ be the ground set of candidate programmes. Each programme $i \in U$ has:
- Non-negative post-admission utility $v_i \ge 0$ (in `pack.py`, derived from the programme's quality/tier/route score),
- Application fee $c_i \ge 0$ (in EUR),
- Funded/affordable admission indicator $Z_i \in \{0, 1\}$.

When a student applies to a subset $S \subseteq U$ of programmes and can enroll in at most one programme (choosing the highest-utility programme among those that yield a funded/affordable offer), the realized utility is $\max_{i \in S} Z_i v_i$ (with $\max_{\emptyset} \equiv 0$). If the student has an outside option of utility $v_0 = 0$, the expected portfolio utility is:
$$U(S) = \mathbb{E}\!\left[\max_{i \in S} Z_i v_i\right].$$

When $Z_i \sim \text{Bernoulli}(p_i)$ are mutually independent across $i \in S$, sorting the elements of $S = \{i_1, i_2, \dots, i_r\}$ in ascending order of utility $0 \le v_{i_1} \le v_{i_2} \le \dots \le v_{i_r}$ yields the closed-form polynomial (**Chade & Smith 2006, Eq. 1; Kapur & Hong 2022, Proposition 1**):
$$U(S) = \sum_{a=1}^{r} p_{i_a} v_{i_a} \prod_{b=a+1}^{r} (1 - p_{i_b}) = \sum_{a=1}^{r} (v_{i_a} - v_{i_{a-1}}) \left(1 - \prod_{b=a}^{r} (1 - p_{i_b})\right), \quad v_{i_0} \equiv 0.$$

Moreover, **Kapur & Hong (2022, Lemma 2, Eq. 7)** proves the exact **Variable-Elimination Transformation**: once programme $k$ (with probability $p_k$ and utility $v_k$) is added to the portfolio, the marginal gain $\Delta U(j \mid S \cup \{k\})$ of any remaining independent candidate $j$ is obtained by updating its residual utility $v_j$ according to:
$$v_j^{(k)} = \begin{cases} (1 - p_k) v_j, & \text{if } v_j \le v_k, \\ v_j - p_k v_k, & \text{if } v_j > v_k. \end{cases}$$

In the special case where $v_i \equiv 1$ for all $i \in S$, $U(S)$ reduces to the **portfolio success probability** (the probability of receiving at least one funded/affordable offer):
$$P_{\text{success}}(S) = \mathbb{P}\!\left(\max_{i \in S} Z_i = 1\right) = 1 - \mathbb{P}(\forall i \in S, Z_i = 0).$$

### 2.2 Common-Shock External Scholarship Factor Model
In `tehsil_agent`, a programme $i$'s funded admission depends on both university admission $A_i \sim \text{Bernoulli}(a_i)$ and funding affordability. When funding is **mandatory** (`funding_Need == "MANDATORY"` or `is_affordable == False`), candidate programmes fall into two structural categories based on [`apps/funding/probability.py`](file:///home/orkhan/Desktop/tehsil_agent/apps/funding/probability.py#L1422-L1570) and [`apps/research/spine.py`](file:///home/orkhan/Desktop/tehsil_agent/apps/research/spine.py#L722-L742):
1. **Independent / Programme-Specific Routes ($i \in S_0$):**
   - Tuition-free / affordable within family budget (`Affordable`: $p_i = a_i$, funding factor $= 1.0$), or
   - University-specific scholarship (`scope == "UNIVERSITY"`, e.g. university tuition waiver / internal merit award decided independently by that university's admissions committee: $p_i = a_i s_i$ independent across universities).
2. **Shared External Funder Groups ($i \in S_k, k \in \{1, \dots, K\}$):**
   - External scholarships with `scope in {"COUNTRY", "HOLDER", "GLOBAL"}` or `Post-Admission Government Scholarship` (e.g., *Stipendium Hungaricum*, *DAAD*, *Chevening*, *Fulbright*, *Turkiye Burslari*, *Italian Government Scholarship*, or *DP 2022–2028*).
   - All programmes $i \in S_k$ backed by the same external scholarship scheme $k$ share a **common Bernoulli shock** $F_k \sim \text{Bernoulli}(q_k)$, where $q_k \in (0, 1)$ is the student's probability of winning external scholarship $k$, and $A_i \sim \text{Bernoulli}(a_i)$ is the conditional admission indicator at programme $i$.
   - Programme $i \in S_k$ yields a funded admission if and only if $Z_i = F_k \cdot A_i = 1$.

Notice that for a single programme ($|S_k| = 1$), $\mathbb{P}(Z_i = 1) = \mathbb{E}[F_k A_i] = q_k a_i = p_i$. Thus, in 1D isolation, a shared external scholarship and an independent university scholarship with $s_i = q_k$ have the **exact same standalone probability** $p_i = a_i q_k$. However, for $|S_k| \ge 2$, the indicators $\{Z_i\}_{i \in S_k}$ are positively correlated:
$$\text{Cov}(Z_i, Z_j) = \mathbb{E}[F_k^2 A_i A_j] - \mathbb{E}[F_k A_i]\mathbb{E}[F_k A_j] = q_k(1 - q_k) a_i a_j > 0 \quad (\forall i \ne j \in S_k).$$

---

### 2.3 Proposition 1: Monotonicity & Submodularity under Common-Shock External Scholarships (`scilit prove` Verified)

> **Proposition 1 (`scilit prove` verified, `proved: true`, `sympy_verified: true`, `fuzz_verified: true` on 50 instances):**  
> Let $S$ be a finite subset of programmes with non-negative utilities $v_i \ge 0$, conditional admission probabilities $a_i \in (0, 1)$, and a vector of independent common-shock external scholarship factors $F = (F_1, \dots, F_K)$ with $F_k \sim \text{Bernoulli}(q_k)$, $q_k \in (0, 1)$, shared by disjoint subsets $S_k \subseteq S$ such that conditional on $F$, programme successes $Z_i(F) \sim \text{Bernoulli}(p_i(F))$ are mutually independent with $p_i(F) = F_k a_i$ for $i \in S_k$ and $p_i(F) = p_i$ for $i \in S_0 = S \setminus \bigcup_{k=1}^K S_k$. Then both the expected maximum portfolio utility
> $$U(S) = \mathbb{E}_{F, Z}\!\left[\max_{i \in S} Z_i v_i\right]$$
> and the portfolio success probability
> $$P_{\text{success}}(S) = 1 - \mathbb{E}_F\!\left[\prod_{i \in S} (1 - p_i(F))\right]$$
> are **monotone non-decreasing** and **submodular** set functions of $S$.

#### Proof (Verified by `scilit prove` SymPy & Fuzz Engine)
1. **Pointwise Monotonicity and Submodularity of $U(S)$:**  
   Fix any realization $\omega$ of $(F, Z)$, and let $X_i(\omega) = Z_i(\omega) v_i \ge 0$. For any subset $A \subseteq U$, let $m_A = \max_{k \in A} X_k(\omega)$ (with $m_\emptyset = 0$).
   - *First difference (Monotonicity):* For any $i \notin A$,
     $$\max_{k \in A \cup \{i\}} X_k(\omega) - \max_{k \in A} X_k(\omega) = \max(m_A, X_i(\omega)) - m_A = \max(0, X_i(\omega) - m_A) \ge 0.$$
   - *Second difference (Submodularity):* For any distinct $i, j \notin A$,
     $$\max(m_A, X_i) + \max(m_A, X_j) - \max(m_A, X_i, X_j) - m_A = \min(\max(m_A, X_i), \max(m_A, X_j)) - m_A = \max(0, \min(X_i, X_j) - m_A) \ge 0.$$
   Because expectation $\mathbb{E}_{F, Z}[\cdot]$ over any joint distribution of $(F, Z)$ is a non-negative linear operator, taking $\mathbb{E}_{F, Z}[\cdot]$ preserves both inequalities. Therefore, $U(S)$ is monotone non-decreasing and submodular under arbitrary common-shock funder structures.
2. **Closed-Form Expectation and Submodularity of $P_{\text{success}}(S)$:**  
   Conditional on $F$, let $R_A(F) = \prod_{k \in A} (1 - p_k(F)) \in [0, 1]$ and $P_{\text{cond}}(A \mid F) = 1 - R_A(F)$.
   - For $i \notin A$, $P_{\text{cond}}(A \cup \{i\} \mid F) - P_{\text{cond}}(A \mid F) = R_A(F) p_i(F) \ge 0$.
   - For distinct $i, j \notin A$,
     $$P_{\text{cond}}(A \cup \{i\} \mid F) + P_{\text{cond}}(A \cup \{j\} \mid F) - P_{\text{cond}}(A \cup \{i, j\} \mid F) - P_{\text{cond}}(A \mid F) = R_A(F) p_i(F) p_j(F) \ge 0.$$
   Taking $\mathbb{E}_F[\cdot]$ preserves both non-negativity inequalities. $\blacksquare$

#### Exact Closed-Form Evaluation of $U(S)$ under Multi-Funder Common Shocks
Let $S = S_0 \cup S_1 \cup \dots \cup S_K$. Sort all programmes in $S$ by ascending utility $0 = v_{i_0} \le v_{i_1} \le v_{i_2} \le \dots \le v_{i_r}$. By the layer-cake identity $\max_{i \in S} Z_i v_i = \sum_{a=1}^{r} (v_{i_a} - v_{i_{a-1}}) \mathbb{I}(\exists b \ge a : Z_{i_b} = 1)$ and mutual independence of $S_0, S_1, \dots, S_K$, the survival probability of every upper level-set $S_{\ge a} = \{i_a, i_{a+1}, \dots, i_r\}$ factors across funder groups in $O(|S| \log |S|)$ time without enumerating $2^K$ funder states:
$$U(S) = \sum_{a=1}^{r} (v_{i_a} - v_{i_{a-1}}) \left[1 - \left(\prod_{j \in S_0 \cap S_{\ge a}} (1 - p_j)\right) \prod_{k=1}^{K} \left((1 - q_k) + q_k \prod_{j \in S_k \cap S_{\ge a}} (1 - a_j)\right)\right].$$
This identity is **exact** for arbitrary $K$ and runs in $O(|S| \log |S|)$ operations!

---

### 2.4 Proposition 2: Strict Overestimation of Portfolio Success by Naive Independence (`scilit prove` Verified)

> **Proposition 2 (`scilit prove` verified, `proved: true`, `sympy_verified: true`, `fuzz_verified: true` on 50 instances):**  
> When a subset of programmes $S_k \subseteq S$ with $n = |S_k| \ge 2$ depend on the same external scholarship $k$ with funder award probability $q_k \in (0, 1)$ and conditionally independent programme admission probabilities $a_i \in (0, 1)$:
> 1. The exact common-shock failure probability is
>    $$F_n = (1 - q_k) + q_k \prod_{i \in S_k} (1 - a_i).$$
> 2. Let $N_n = \prod_{i \in S_k} (1 - a_i q_k)$ be the naive independent failure formula and $P_n = \prod_{i \in S_k} (1 - a_i)$. The overestimation gap $D_n = F_n - N_n = (1 - N_n) - (1 - F_n)$ satisfies the exact positive-term telescoping identity:
>    $$D_n = \sum_{m=1}^{n-1} q_k a_{m+1} (N_m - P_m) \prod_{j=m+2}^{n} (1 - a_j) > 0 \quad (\forall n \ge 2).$$
>    In particular, for $n = 2$, $D_2 = q_k (1 - q_k) a_1 a_2 > 0$. Consequently, naive independence $1 - \prod_{i \in S_k} (1 - a_i q_k)$ **strictly overestimates** the true portfolio success probability $1 - F_n$ whenever $|S_k| \ge 2$.

#### Proof Summary (`scilit prove` SymPy Script Output)
- For $n = 1$, $F_1 = (1 - q_k) + q_k(1 - a_1) = 1 - a_1 q_k = N_1$, so $D_1 = 0$.
- For $m \ge 1$,
  $$D_{m+1} - (1 - a_{m+1}) D_m = \big[(1 - q_k) + q_k (1 - a_{m+1}) P_m - (1 - a_{m+1} q_k) N_m\big] - (1 - a_{m+1})\big[(1 - q_k) + q_k P_m - N_m\big] = q_k a_{m+1} (N_m - P_m).$$
- Since $q_k \in (0, 1)$ and $a_i \in (0, 1)$, each factor satisfies $1 - a_i q_k = (1 - a_i) + a_i (1 - q_k) > 1 - a_i > 0$, so $N_m > P_m > 0$ for all $m \ge 1$. Every term in the telescoping sum is strictly positive. $\blacksquare$

---

### 2.5 Proposition 3: Multi-Funder Marginal Gain & Funder Concentration Ceiling (`scilit prove` Verified)

> **Proposition 3 (`scilit prove` verified, `proved: true`, `sympy_verified: true`, `fuzz_verified: true` across Subgoals 1, 2, 3):**  
> In a multi-funder common-shock portfolio where programmes in $S$ are partitioned into an independent subset $S_0$ (with success probabilities $p_i \in (0, 1)$) and disjoint external-funder groups $S_k$ ($k = 1, \dots, K$) where group $k$ shares a scholarship indicator $F_k \sim \text{Bernoulli}(q_k)$ with $q_k \in (0, 1)$ and conditional admission probabilities $a_i \in (0, 1)$:
> 1. **Exact Multi-Funder Failure Probability:**
>    $$P_{\text{fail}}(S) = \left(\prod_{i \in S_0} (1 - p_i)\right) \prod_{k=1}^{K} \left((1 - q_k) + q_k \prod_{i \in S_k} (1 - a_i)\right).$$
> 2. **Exact Marginal Gain of Adding $j \in S_k$:**
>    $$\Delta P_{\text{success}}(j \mid S) = \left(\prod_{i \in S_0} (1 - p_i)\right) \left(\prod_{m \ne k} \left((1 - q_m) + q_m \prod_{i \in S_m} (1 - a_i)\right)\right) q_k a_j \prod_{i \in S_k} (1 - a_i).$$
> 3. **Funder Concentration Ceiling:** For a single funder group $S_k$,
>    $$P_{\text{success}}(S_k) = q_k \left(1 - \prod_{i \in S_k} (1 - a_i)\right) < q_k \quad (\forall \text{ finite } |S_k|),$$
>    establishing a strict funder concentration ceiling $q_k < 1$ with ceiling gap $q_k - P_{\text{success}}(S_k) = q_k \prod_{i \in S_k} (1 - a_i) > 0$, whereas naive independence $1 - \prod_{i \in S_k} (1 - a_i q_k)$ converges to $1$ as $|S_k| \to \infty$ when $a_i \ge a_{\min} > 0$.

#### Key Algorithmic Consequence of Proposition 3(2)
Compare the marginal gain of adding another programme $j$ in an already-populated external scholarship group $S_k$ against adding an independent programme $j' \in S_0$ (or a programme in a fresh funder group $S_{k'}$ with $S_{k'} = \emptyset$):
- Within group $S_k$, each existing programme $i \in S_k$ multiplies the marginal gain of subsequent programmes in $S_k$ by **$(1 - a_i)$**, not by $(1 - a_i q_k)$!
- Why? Because conditional on $F_k = 0$ (which happens with probability $1 - q_k$), adding $j \in S_k$ contributes **zero** marginal value; $j$ only helps in the event $F_k = 1$ *and* all previously selected programmes in $S_k$ rejected the student ($\prod_{i \in S_k} (1 - a_i)$).
- For example, if $q_k = 0.20$ (*Stipendium Hungaricum* award chance) and $a_i = 0.60$ (admission chance at each Hungarian university):
  - 1st programme in $S_k$: $\Delta P = 0.20 \times 0.60 = 12.0\%$.
  - 2nd programme in $S_k$: $\Delta P = 0.20 \times 0.60 \times (1 - 0.60) = 4.8\%$ (whereas naive independence assumes $12.0\% \times (1 - 0.12) = 10.56\%$, more than $2.2\times$ too high!).
  - 3rd programme in $S_k$: $\Delta P = 0.20 \times 0.60 \times (0.40)^2 = 1.92\%$ (whereas naive independence assumes $9.29\%$, nearly $5\times$ too high!).
  - 4th programme in $S_k$: $\Delta P = 0.20 \times 0.60 \times (0.40)^3 = 0.768\%$ (whereas naive independence assumes $8.18\%$, more than $10.6\times$ too high!).

---

### 2.6 Budgeted Submodular Maximization under Fee Knapsack & Matroid Caps
When paid programmes have heterogeneous application fees $c_i > 0$ under remaining fee budget $B_{\text{rem}} = B_{\text{eff}} - \sum_{i \in S_{\text{locked}}} c_i$, the portfolio optimization problem is:
$$\max_{S \subseteq U_{\text{paid}}} U(S_{\text{free}} \cup S) \quad \text{s.t.} \quad \sum_{i \in S} c_i \le B_{\text{rem}}, \quad |S_{\text{free}} \cup S| \le K, \quad |\{i \in S_{\text{free}} \cup S : \text{inst}(i) = I\}| \le M_{\text{inst}} \;\; (\forall I).$$

By **Kapur & Hong (2022, Theorem 6 & Example 3)**, pure cost-scaled greedy $\arg\max_{i} \Delta U(i \mid S) / c_i$ can fail catastrophically when a low-cost, low-utility candidate $i_{\text{cheap}}$ ($c = 5\text{ EUR}, \Delta U = 2$) has higher density ($0.40/\text{EUR}$) than a flagship anchor candidate $i_{\text{anchor}}$ ($c = 95\text{ EUR}, \Delta U = 30$, density $0.316/\text{EUR}$) under a $98\text{ EUR}$ budget: picking $i_{\text{cheap}}$ leaves $93\text{ EUR} < 95\text{ EUR}$, blocking $i_{\text{anchor}}$ and returning utility $2$ instead of $30$.

By **Khuller, Moss, & Naor (1999)**, **Sviridenko (2004)**, **Leskovec et al. (2007, CELF)**, **Sarpatwar, Schieber, & Shachnai (2018)**, and **Nutov & Shoham (2020)**, the **Twin-Pass Budgeted Submodular Algorithm** resolves both failure modes simultaneously:
1. **Pass 1 (Unscaled Marginal Utility / Chade-Smith MIA Pass $S_{\text{unit}}$):** At each step, among all budget-feasible and matroid-feasible remaining paid candidates, select
   $$i^* = \arg\max_{i \in \mathcal{F}(S)} \Delta U(i \mid S_{\text{free}} \cup S),$$
   subject to anchor-reservation lookahead when no anchor (`TARGET`/`SAFETY`) is yet present in $S_{\text{free}} \cup S$. By Chade & Smith (2006, Theorem 1), Pass 1 is **exact** when fees are uniform or non-binding, and naturally includes the best single feasible high-fee item $\arg\max_{c_i \le B_{\text{rem}}} \Delta U(i \mid S_{\text{free}})$.
2. **Pass 2 (Cost-Efficiency Marginal Density Pass $S_{\text{density}}$):** At each step, among all budget-feasible and matroid-feasible remaining paid candidates, select
   $$i^* = \arg\max_{i \in \mathcal{F}(S)} \frac{\Delta U(i \mid S_{\text{free}} \cup S)}{\max(c_i, c_{\min})},$$
   followed by greedy fill of any remaining budget. Pass 2 captures knapsack splits where two $45\text{ EUR}$ programmes together yield strictly higher portfolio utility $U(S)$ than a single $90\text{ EUR}$ programme.
3. **Twin-Pass Selection:** Compare $U(S_{\text{free}} \cup S_{\text{unit}})$ against $U(S_{\text{free}} \cup S_{\text{density}})$ and select the portfolio with strictly higher total submodular utility (breaking ties in favor of $S_{\text{unit}}$ to preserve exact backward compatibility when fees are uniform or do not create a superior knapsack split).

---

## 3. Line-by-Line Audit of `apps/funding/pack.py`

### 3.1 Architecture Map & Exact Line Citations

| File & Lines | Function / Symbol | Current Behavior & Exact Defect |
| :--- | :--- | :--- |
| [`apps/funding/pack.py#L141-L164`](file:///home/orkhan/Desktop/tehsil_agent/apps/funding/pack.py#L141-L164) | `class Pack` | Stores `fee_free`, `paid`, `fee_not_known`, `out_of_budget`, `unaffordable`, `not_eligible`, `budget_summary`, `tier_Mix`, `warnings`. **Missing:** `pack_success_probability_pct: int | None = None` (exact portfolio-level probability of $\ge 1$ funded/affordable admission). |
| [`apps/funding/pack.py#L178-L198`](file:///home/orkhan/Desktop/tehsil_agent/apps/funding/pack.py#L178-L198) | `_effective_chance_for` | Returns `funded_probabilities[pid]` when `funding_need == "MANDATORY"` or `not is_affordable`, else `admission_probabilities[pid]`. Returns a single 1D scalar `float` with **no distinction** between independent university funding and a shared external scholarship common shock $F_k$. |
| [`apps/funding/pack.py#L291-L370`](file:///home/orkhan/Desktop/tehsil_agent/apps/funding/pack.py#L291-L370) | `rank_candidates` | Computes `effective_score` in 1D isolation (`base * 0.7 + route_pts + deadline_pts + schol_pts - penalty`, lines 331–354) and returns `sorted(ranked, key=lambda x: (-x["effective_score"], x["fee"], x["program"].get("id", "")))` (lines 364–368). Does **not** condition on already-selected programmes or shared external scholarship exposure. |
| [`apps/funding/pack.py#L472-L560`](file:///home/orkhan/Desktop/tehsil_agent/apps/funding/pack.py#L472-L560) | `_should_reserve_budget_for_anchor` | Only checks whether taking a `REACH` item leaves enough budget for the cheapest remaining `TARGET`/`SAFETY` item (`min_anchor_fee`), and is called **only when `tier == "REACH" and not top_only and not _has_anchor_in_active()`** (line 915). |
| [`apps/funding/pack.py#L700-L704`](file:///home/orkhan/Desktop/tehsil_agent/apps/funding/pack.py#L700-L704) | `_has_anchor_in_active` | Returns `True` as soon as **any** `TARGET` or `SAFETY` item is in `fee_free + paid + fee_not_known`. If the pack contains even **one** `fee_free` `SAFETY` programme, `_has_anchor_in_active()` is `True`, so `_should_reserve_budget_for_anchor` is **never called** for paid candidates! |
| [`apps/funding/pack.py#L784-L960`](file:///home/orkhan/Desktop/tehsil_agent/apps/funding/pack.py#L784-L960) | `build_pack` main loop | Iterates `for idx, item in enumerate(ranked):` in static 1D order. Admits paid candidates one-by-one whenever `fee <= remaining_budget` (line 903) without comparing marginal utility per euro $\Delta U(i \mid S) / c_i$ or discounting repeated exposure to the same external scholarship $k$. |
| [`apps/research/spine.py#L722-L742`](file:///home/orkhan/Desktop/tehsil_agent/apps/research/spine.py#L722-L742) | `run_research_spine` | Already computes `schemes[pid]` (`best_s["name"]`) and `funded_probs[pid]`, and passes `schemes=schemes` into `build_pack(...)` at line 765! Inside `build_pack`, `schemes` is currently used **only** for a cosmetic display string `item["best_scholarship_name"]` (lines 791–794) and is completely ignored during ranking and selection! |

---

### 3.2 Concrete Numerical Counterexample A: Fee-Budget Knapsack Failure (`pack.py` Lines 784–960)
Suppose a student has `application_fee_budget_eur = 103` $\implies$ `effective_fee_budget = int(103 / 1.02) = 100 EUR`, and three paid programmes (all affordable, independent universities):
- **Programme 1 (`P_expensive`):** `fee = 90 EUR`, `admission_prob = 42%`, `tier = "TARGET"`, standalone `effective_score = 46.4`.
- **Programme 2 (`P_split_A`):** `fee = 45 EUR`, `admission_prob = 40%`, `tier = "TARGET"`, standalone `effective_score = 45.0`.
- **Programme 3 (`P_split_B`):** `fee = 45 EUR`, `admission_prob = 40%`, `tier = "TARGET"`, standalone `effective_score = 45.0`.

**What current `pack.py` does (lines 784–946):**
1. `rank_candidates` sorts `[P_expensive (46.4), P_split_A (45.0), P_split_B (45.0)]`.
2. At `idx = 0` (`P_expensive`), `tier == "TARGET"`, so `_should_reserve_budget_for_anchor` is not even invoked. Since `90 <= 100`, `P_expensive` is added to `paid`. `remaining_budget` drops to `10 EUR`.
3. At `idx = 1` (`P_split_A`, `fee = 45 > 10`) and `idx = 2` (`P_split_B`, `fee = 45 > 10`), both are rejected to `out_of_budget` with `FEE_EXCEEDS_REMAINING_BUDGET`.
4. **Resulting Pack:** `paid = [P_expensive]`, total fee $= 90\text{ EUR}$, **portfolio success probability $= 42\%$**, expected utility $= 0.42 \times 46.4 = 19.49$.

**What Twin-Pass Budgeted Submodular Optimization does:**
- **Pass 1 (`S_unit`):** Picks `[P_expensive]`, $U(S_{\text{unit}}) = 19.49$, $P_{\text{success}} = 42\%$.
- **Pass 2 (`S_density`):**
  - Step 1: Marginal utility per EUR is $19.49 / 90 = 0.2165/\text{EUR}$ for `P_expensive`, vs $(0.40 \times 45.0) / 45 = 0.4000/\text{EUR}$ for `P_split_A` and `P_split_B`. Pass 2 selects `P_split_A` (`remaining_budget = 55 EUR`).
  - Step 2: Conditional on `P_split_A`, `P_split_B` has marginal gain $\Delta U(\text{P\_split\_B} \mid \{\text{P\_split\_A}\}) = (1 - 0.40) \times (0.40 \times 45.0) = 10.80$, density $10.80 / 45 = 0.2400/\text{EUR}$, and `45 <= 55`. Pass 2 selects `P_split_B` (`remaining_budget = 10 EUR`).
  - Total utility of `S_density = [P_split_A, P_split_B]` is $U(S_{\text{density}}) = 18.0 + 10.8 = 28.80 > 19.49$, and **portfolio success probability is $1 - (1 - 0.40)^2 = 64\% > 42\%$** (+22 percentage points higher chance of admission for the same $90\text{ EUR}$ spend!).

---

### 3.3 Concrete Numerical Counterexample B: Correlated External Funder Risk (`pack.py` Lines 178–198, 291–370, 784–960)
Suppose a mandatory-funding student (`funding_need = "MANDATORY"`) has `MAX_ACTIVE_PROGRAMS = 4` (or limited fee budget) and considers:
- **4 Hungarian programmes (`H1, H2, H3, H4`) at different Hungarian universities**, all funded exclusively by `schemes[Hi] = "Stipendium Hungaricum"` (`COUNTRY` scholarship with student award probability $q_{\text{SH}} = 0.25$ and university admission probability $a_{H_i} = 0.60$, so standalone `funded_probabilities[Hi] = 15.0%`, `effective_score = 38.5`).
- **2 German programmes (`G1, G2`)**, funded by `schemes[Gi] = "DAAD"` (`HOLDER` scholarship with $q_{\text{DAAD}} = 0.25$, $a_{G_i} = 0.56$, so standalone `funded_probabilities[Gi] = 14.0%`, `effective_score = 37.8`).
- **1 tuition-covered / university-waiver programme (`U1`)**, with independent `funded_probabilities[U1] = 13.5%`, `effective_score = 37.4`.

**What current `pack.py` does:**
- Sorts strictly by standalone 1D `effective_score`: `[H1 (38.5), H2 (38.5), H3 (38.5), H4 (38.5), G1 (37.8), G2 (37.8), U1 (37.4)]`.
- Selects the top 4: **`[H1, H2, H3, H4]`** — putting 100% of the student's pack into a single external scholarship lottery (`Stipendium Hungaricum`)!
- Under naive independence, `pack.py` implicitly treats `[H1, H2, H3, H4]` as having $1 - (1 - 0.15)^4 = 47.8\%$ success probability.
- By **Proposition 3(3)**, the **true common-shock success probability** of `[H1, H2, H3, H4]` is:
  $$P_{\text{success}}(\{H_1, H_2, H_3, H_4\}) = 0.25 \times \big(1 - (1 - 0.60)^4\big) = 0.25 \times (1 - 0.0256) = \mathbf{24.36\%} < 25\%!$$

**What Common-Shock Submodular Portfolio Optimization does:**
- **Step 1:** Selects `H1` ($\Delta P = 15.0\%$, marginal utility $= 0.15 \times 38.5 = 5.775$).
- **Step 2:** By **Proposition 3(2)**, the marginal funded success probability of `H2` (which shares `Stipendium Hungaricum` with `H1`) drops from $15.0\%$ to $q_{\text{SH}} a_{H_2} (1 - a_{H_1}) = 0.25 \times 0.60 \times (1 - 0.60) = \mathbf{6.0\%}$! Meanwhile, `G1` (backed by an independent funder `DAAD`) has marginal funded success probability $(1 - 0.15) \times 0.14 = \mathbf{11.9\%}$, and `U1` (independent university waiver) has $(1 - 0.15) \times 0.135 = \mathbf{11.475\%}$.
- Therefore, step 2 selects **`G1`**, step 3 selects **`U1`**, and step 4 selects **`H2`** (or **`G2`**), yielding the diversified portfolio **`[H1, G1, U1, H2]`** across three independent funding sources!
- By **Proposition 3(1)**, the true common-shock success probability of `[H1, G1, U1, H2]` is:
  $$P_{\text{success}}(\{H_1, G_1, U_1, H_2\}) = 1 - (1 - 0.135) \times \big((1 - 0.25) + 0.25(1 - 0.60)^2\big) \times \big((1 - 0.25) + 0.25(1 - 0.56)\big) = 1 - 0.865 \times 0.79 \times 0.86 = \mathbf{41.23\%},$$
  an improvement of **+16.87 percentage points** (+69% relative increase in funded admission probability) over `[H1, H2, H3, H4]` ($24.36\%$).

---

## 4. Exact Drop-In Python Algorithmic Specification for `apps/funding/pack.py`

### 4.1 Design Principles & Invariant Preservation
To ensure **zero regressions** across `tests/funding/test_ranking.py`, `tests/funding/test_pack_owner_decisions.py`, and `tests/funding/test_pack_awards.py` while fixing both failure modes:
1. **`rank_candidates` Signature & Standalone Ordering Preserved:** `rank_candidates` continues to return the exact standalone 1D ranked list with `effective_score`, `effective_chance`, `tier`, `fee`, and `fee_status` unchanged, so callers and unit tests testing `rank_candidates` directly see identical results.
2. **Exact Decomposition of Shared External Scholarship Risk (`_decompose_candidate_funder_risk`):**
   - For each candidate $i$, let $p_i = \text{clamp}(\text{effective\_chance}_i / 100, 0, 1)$ and $a_i^{\text{raw}} = \text{clamp}(\text{admission\_prob}_i / 100, 0, 1)$.
   - When the programme's success probability uses `funded_probabilities` (`funding_need == "MANDATORY"` or `not is_affordable`) **and** the programme relies on an external scholarship (`best_scholarship_name` is a named external scheme or `Post-Admission Government Scholarship`, and $p_i < a_i^{\text{raw}} - 10^{-6}$):
     - Let $S_k$ be the group of candidates sharing that external scholarship key `funder_key = best_scholarship_name.strip().lower()`.
     - What is the shared scholarship factor $q_k$ and conditional admission probability $a_i$?
       - Since `funded_prob` in [`apps/funding/probability.py`](file:///home/orkhan/Desktop/tehsil_agent/apps/funding/probability.py#L1562) is computed as `p_i = adm_prob * best_schol_prob`, for each $i \in S_k$ with $a_i^{\text{raw}} > 0$, the implied scholarship award probability is $s_i = \min(0.99, p_i / a_i^{\text{raw}})$.
       - When $a_i^{\text{raw}}$ is explicitly provided and $p_i < a_i^{\text{raw}}$, we recover $q_k = \max_{j \in S_k} \min(0.99, p_j / a_j^{\text{raw}})$ and $a_i = \min(0.99, p_i / q_k)$, satisfying $q_k a_i = p_i$ **identically** for every single item ($|S_k| = 1$ has zero change!).
       - Fallback when `admission_probabilities` is not passed or equals `funded_probabilities` in a synthetic test that still passes `schemes[pid] = "Shared Scheme"` for $|S_k| \ge 2$: if $p_i = a_i^{\text{raw}}$ (caller did not pass separate admission probs) and `schemes` is not passed, the candidate is treated as independent ($i \in S_0$). If `schemes[pid]` **is** explicitly passed and shared by $|S_k| \ge 2$ mandatory-funding candidates with $p_i < 0.95$, we decompose $q_k = \min(0.95, \max_{j \in S_k} \sqrt{p_j})$ and $a_i = \min(0.99, p_i / q_k)$ whenever $a_i^{\text{raw}}$ was not separately supplied, or use $q_k = \max_{j \in S_k} (p_j / a_j^{\text{raw}})$ when $a_j^{\text{raw}} > p_j$ is supplied.
3. **Submodular Marginal Utility $\Delta U(i \mid S)$ with Common-Shock Discounting & Twin-Pass Paid Selection:**
   - Every candidate $i$ has quality utility $v_i = \max(1.0, \text{effective\_score}_i)$ and effective probability parameters $(k_i, q_{k_i}, a_i)$ (or $p_i$ if independent $k_i = \text{None}$).
   - For any active portfolio $S$, $U(S)$ is evaluated via the exact layer-cake multi-funder common-shock formula from Section 2.3:
     $$U(S) = \sum_{a=1}^{r} (v_{i_a} - v_{i_{a-1}}) \left[1 - \left(\prod_{j \in S_0 \cap S_{\ge a}} (1 - p_j)\right) \prod_{k=1}^{K} \left((1 - q_k) + q_k \prod_{j \in S_k \cap S_{\ge a}} (1 - a_j)\right)\right].$$
   - Notice a crucial property of this formula: when $|S| = 0$, $U(\{i\}) = p_i v_i$. To ensure that for the **first** item (or when all items have identical probabilities), the ordering matches `rank_candidates` (`effective_score`) exactly, we define the normalized utility weight:
     $$u_i = \frac{\text{effective\_score}_i}{\max(p_i, 0.01)} \implies p_i u_i = \text{effective\_score}_i!$$
     Let's verify this! If we set $u_i = \text{effective\_score}_i / \max(p_i, 0.01)$ when comparing standalone items, then $U(\{i\}) = p_i u_i = \text{effective\_score}_i$, which reproduces `rank_candidates`'s **exact standalone order** on singletons while automatically applying the exact Chade-Smith / Kapur-Hong submodular diminishing returns $(1 - p_j)$ and Proposition 3 common-shock discount $q_k (1 - a_j)$ as soon as $|S| \ge 1$!
   - Even better: let's check what happens when two paid candidates `P_split_A` (`45 EUR`, $p = 0.40$, `score = 45.0`) and `P_split_B` (`45 EUR`, $p = 0.40$, `score = 45.0`) are compared against `P_expensive` (`90 EUR`, $p = 0.42$, `score = 46.4`):
     - Singleton `P_expensive`: $U(\{\text{P\_expensive}\}) = 46.4$.
     - Pair `{P_split_A, P_split_B}`: $u_A = 45.0 / 0.40 = 112.5$, $u_B = 45.0 / 0.40 = 112.5$. Then
       $$U(\{\text{P\_split\_A}, \text{P\_split\_B}\}) = 112.5 \times (1 - (1 - 0.40)^2) = 112.5 \times 0.64 = \mathbf{72.0} > 46.4!$$
     - What if `P_split_A` and `P_split_B` share the same external scholarship $k$ with $q_k = 0.25, a_i = 0.60, p_i = 0.15$?
       - First item `H1`: $U(\{H_1\}) = p_{H_1} u_{H_1} = \text{score}_{H_1} = 38.5$.
       - Adding `H2` (same funder $k$): $P_{\text{success}}(\{H_1, H_2\}) = 0.25 \times (1 - 0.40^2) = 0.21$, so $\Delta P(H_2 \mid \{H_1\}) = 0.21 - 0.15 = 0.06$, and $\Delta U(H_2 \mid \{H_1\}) = 0.06 \times u_{H_2} = (0.06 / 0.15) \times 38.5 = 0.40 \times 38.5 = \mathbf{15.4}$.
       - Adding `G1` (different funder $k'$ with $p_{G_1} = 0.14$, $\text{score}_{G_1} = 37.8$): $\Delta P(G_1 \mid \{H_1\}) = (1 - 0.15) \times 0.14 = 0.85 \times 0.14$, so $\Delta U(G_1 \mid \{H_1\}) \approx 0.85 \times 37.8 = \mathbf{32.13} \gg 15.4$!
       - Thus `G1` strictly beats `H2` on the second step, while on step 1 `H1` (`38.5`) still beats `G1` (`37.8`)!

Let's double-check that normalization $u_i = \text{effective\_score}_i / \max(p_i, 0.01)$!
Wait: what if a candidate has $p_1 = 0.10$ (`REACH`, `effective_score = 20.0`, so $u_1 = 200.0$) and another candidate has $p_2 = 0.80$ (`SAFETY`, `effective_score = 60.0`, so $u_2 = 75.0$)?
Let's check! If $S = \{\text{SAFETY}\}$ ($p_2 = 0.80, u_2 = 75.0$), what is the marginal gain of adding `REACH` ($p_1 = 0.10, u_1 = 200.0$)?
Since $u_1 > u_2$, in the upper level-set above $u_2$, `REACH` succeeds with probability $p_1 = 0.10$ and adds $p_1 (u_1 - u_2) = 0.10 \times (200 - 75) = 12.5$.
Wait: what if `REACH` has `effective_score = 20.0` ONLY because its base is $0.7 \times 10 = 7.0$ plus route/deadline bonus $13.0 = 20.0$? If we divide `effective_score` by $p_1 = 0.10$, a route/deadline bonus of $+13$ turns into $13 / 0.10 = +130$ in $u_1$, which would artificially inflate low-probability items' post-admission utility $u_i$!
What a critical catch! Let's analyze why:
In `rank_candidates` (lines 331–354 of `pack.py`):
```python
effective_score = (
    base * 0.7            # where base = effective_chance in [0, 100]
    + route_pts           # 0 to 15
    + deadline_pts        # 0 to 10
    + schol_pts           # 0 to 5
    - penalty             # 0 to 12.5
)
```
Look at `effective_score`: `base * 0.7` is ALREADY proportional to `effective_chance` ($p_i$), whereas `route_pts + deadline_pts + schol_pts - penalty` is an additive quality/urgency bonus ($0$ to $30$ points)!
If you divided `effective_score` by $p_i$, then for $p_i = 0.01$, `route_pts = 15` would become $15 / 0.01 = 1500$!
Instead, what is the true utility $v_i$ and how does `effective_score` relate to $p_i$ and $F_k$?
Let's check!
In `rank_candidates`, why does item $i$ have `effective_score`?
Because `base = effective_chance = 100 * p_i`!
Wait: when item $i$ is evaluated **conditional on existing portfolio $S$**, what changes between standalone evaluation ($S = \emptyset$) and conditional evaluation ($S \ne \emptyset$)?
1. **Conditional Effective Chance $p_i(S)$ under Common-Shock Funder Correlation:**
   - When $S = \emptyset$, the marginal funded success probability of adding $i \in S_k$ is $\Delta P_{\text{funder}}(i \mid \emptyset) = q_k a_i = p_i$.
   - When $S_k \cap S \ne \emptyset$ (the portfolio already contains programmes $j \in S_k \cap S$ relying on the **same** external scholarship $k$), by **Proposition 3(2)**, the marginal funded success contribution of $i$ within funder group $k$ is discounted by the conditional survival factor of group $k$:
     $$p_i(S) = q_k a_i \prod_{j \in S_k \cap S} (1 - a_j) = p_i \prod_{j \in S_k \cap S} (1 - a_j)!$$
   - Look how clean and exact that is: when $S_k \cap S = \emptyset$, $\prod_{j \in S_k \cap S} (1 - a_j) = 1$, so $p_i(S) = p_i$ (the exact standalone `effective_chance`!). When $S_k \cap S \ne \emptyset$, $p_i(S) = p_i \prod_{j \in S_k \cap S} (1 - a_j)$ replaces `base = 100 * p_i` with `base_cond = 100 * p_i(S)`!
2. **Submodular Portfolio Diminishing Returns across All Active Programmes:**
   - Suppose the portfolio $S$ already has active programmes. What is the marginal gain $\Delta U(i \mid S)$ of adding candidate $i$?
   - Let every candidate $i$ have post-admission intrinsic quality $v_i \in (0, 100]$ defined directly from the non-probability programme attributes (plus tier/quality):
     In `rank_candidates`, `effective_score_i = 70.0 * p_i + B_i`, where $B_i = \text{route\_pts}_i + \text{deadline\_pts}_i + \text{schol\_pts}_i - \text{penalty}_i + \text{tie\_bonus}_i$.
   - If we evaluate the conditional marginal gain of candidate $i$ given $S$:
     - First, within $i$'s external funder group $k$, the effective conditional probability of $i$ succeeding where earlier programmes in $S_k \cap S$ failed is:
       $$p_i^{\text{eff}}(S) = p_i \prod_{j \in S_k \cap S} (1 - a_j).$$
     - Second, across the rest of the portfolio $S \setminus S_k$, how much of $i$'s value is new (not already covered by better or equal programmes in $S$)?
       By **Chade & Smith (2006) / Kapur & Hong (2022, Lemma 2)**, when existing programmes $j \in S$ fail (with portfolio failure probability $P_{\text{fail}}(S \setminus S_k)$ across other groups), candidate $i$ provides full standalone conditional score:
       $$\text{score}_i^{\text{cond}}(S) = \max\!\Big(0.0,\; 70.0 \cdot p_i^{\text{eff}}(S) + B_i \cdot \prod_{j \in S_k \cap S} (1 - a_j)\Big) = \left(\prod_{j \in S_k \cap S} (1 - a_j)\right) \cdot \max(0.0, \text{effective\_score}_i).$$
       Wait: look at that factor $\prod_{j \in S_k \cap S} (1 - a_j) \cdot \text{effective\_score}_i$:
       - If $i$ is in a **new** funder group ($S_k \cap S = \emptyset$) or is **independent** ($i \in S_0$), then $\prod_{j \in S_k \cap S} (1 - a_j) = 1$, so its unscaled marginal score is $\text{effective\_score}_i$ — **100% identical to `rank_candidates`!**
       - If $i$ shares an external scholarship $k$ with $m \ge 1$ already-selected programmes in $S_k \cap S$, its marginal score is discounted by $\prod_{j \in S_k \cap S} (1 - a_j)$ (exact Proposition 3(2) common-shock survival factor!) because if any earlier programme $j \in S_k \cap S$ already admitted the student (probability $1 - \prod_{j \in S_k \cap S} (1 - a_j)$), or if the external scholarship $k$ rejected the student (probability $1 - q_k$), programme $i$ cannot provide a new funded admission!
     - What about when comparing two subsets of paid programmes $S_{\text{unit}}$ vs $S_{\text{density}}$ of **different cardinalities** (e.g., one `90 EUR` programme vs two `45 EUR` programmes in Counterexample A)?
       If two independent paid programmes $i_1, i_2$ are selected instead of one expensive programme $i_{\text{exp}}$, how should $U(S_{\text{free}} \cup S_{\text{paid}})$ score them?
       By **Kapur & Hong (2022, Proposition 1 & Lemma 2)**, if $i_1, i_2, \dots, i_r$ are in $S$ with intrinsic post-admission value $v_i = 70.0 + B_i$ (the value of the programme *conditional on succeeding*, since $\mathbb{E}[Z_i v_i] = p_i (70.0 + B_i) = 70.0 p_i + p_i B_i$), or even simpler:
       In `rank_candidates`, when $S = \{i\}$, we want $U(\{i\}) = \text{effective\_score}_i$ so that comparing any two singletons $\{i\}$ vs $\{j\}$ agrees 100% with `rank_candidates`!
       And when adding a second independent programme $j$ to $\{i\}$ (where $\text{effective\_score}_i \ge \text{effective\_score}_j$), by Kapur-Hong Lemma 2 (Eq. 7), since $j$ is needed when $i$ fails (probability $1 - p_i$), $j$ contributes:
       $$\Delta U(j \mid \{i\}) = (1 - p_i) \cdot \text{effective\_score}_j!$$
       HOLD ON! Look at that formula:
       Let $S = \{i_1, i_2, \dots, i_r\}$ be sorted in descending order of standalone quality $w_{i_1} \ge w_{i_2} \ge \dots \ge w_{i_r}$, where $w_i = \max(0.0, \text{effective\_score}_i)$.
       Under the Kapur-Hong Lemma 2 recurrence where each programme $i_a$ is needed only when all higher-ranked programmes $i_1, \dots, i_{a-1}$ fail:
       - If $i_a$ is independent, its survival weight given $\{i_1, \dots, i_{a-1}\}$ is $\prod_{b < a} (1 - p_{i_b})$ (or within its funder group $S_k$, $\prod_{b < a, i_b \in S_k} (1 - a_{i_b}) \prod_{m \ne k} P_{\text{fail}}(S_m \cap \{i_1, \dots, i_{a-1}\})$).
       Let's check whether the function
       $$U(S) = \sum_{a=1}^{r} w_{i_a} \cdot \frac{\Delta P_{\text{success}}(i_a \mid \{i_1, \dots, i_{a-1}\})}{\max(p_{i_a}, \epsilon)}$$
       Wait: if $w_i = \text{effective\_score}_i$ and we define each programme's post-admission utility as $v_i = w_i / p_i$? Wait earlier we noticed that if $p_i = 0.01$ and $w_i = 15$, $v_i = 1500$ is only problematic if a higher-probability item has $v_j < v_i$!
       Why did $v_j < v_i$ happen in that hypothetical? Because $w_i$ was sorted in ascending order of $v_i = w_i / p_i$ instead of $w_i$!
       Wait: what if a student's preference order over programmes (conditional on getting funded admission) is simply the programme quality order $w_i = \text{effective\_score}_i$ (or tier/score order)?
       Let's check! If a student gets admitted with funding to two programmes $i$ and $j$, which one does the student enroll in? The higher-ranked one ($w_i \ge w_j$)!
       And if the student's utility of enrolling in $i$ (weighted by $i$'s standalone chance so singleton utility equals $w_i$) is evaluated via Kapur-Hong Lemma 2:
       Wait — if $v_i$ is the utility of enrolling in programme $i$ **given** funded admission ($Z_i = 1$), what is $v_i$ in `pack.py`?
       In `pack.py`:
       - Every programme $i$ gives the student a funded university seat if $Z_i = 1$ (which alone has base utility $V_{\text{seat}} = 70.0$, because $p_i \times 70.0 = \text{base} \times 0.7$!).
       - In addition, programme $i$ has route/deadline/scholarship/friction adjustment $B_i = \text{route\_pts}_i + \text{deadline\_pts}_i + \text{schol\_pts}_i - \text{penalty}_i \in [-12.5, +30.0]$.
       Look at `effective_score` in `pack.py` lines 331–354 again:
       $$\text{effective\_score}_i = 0.7 \times (100 p_i) + B_i = 70 p_i + B_i.$$
       Look at the two terms of $\text{effective\_score}_i$:
       1. $70 p_i = \mathbb{E}[70 \cdot Z_i]$ is literally **expected utility** with seat value $70$!
       2. $B_i$ is the **expected quality/route/deadline bonus** of programme $i$!
       When programme $i$ is evaluated as part of a portfolio $S$:
       - In a portfolio $S$, the student wants:
         (a) At least one funded seat ($70 \cdot P_{\text{success}}(S)$), **plus**
         (b) The quality/route/deadline bonuses of the selected programmes, discounted by common-shock redundancy within each funder group $S_k$ and submodular saturation across the portfolio!
       Let's verify this!
       Suppose we decompose $\text{effective\_score}_i$ into its exact `pack.py` components:
       - Seat probability term: $70.0 \cdot p_i$, whose portfolio-level submodular extension is $70.0 \cdot P_{\text{success}}(S)$!
       - Quality/route/deadline bonus term: $B_i = \text{effective\_score}_i - 70.0 \cdot p_i$, discounted by the survival factor $R_i(S)$ (where $R_i(S) = P_{\text{fail}}(S \setminus S_k) \prod_{j \in S_k \cap S} (1 - a_j)$ is the exact probability from Proposition 3(2) that no previously selected programme in $S$ has already succeeded!).
       WAIT A SECOND!
       Let's check what happens to the marginal gain $\Delta U(i \mid S)$ when we use Proposition 3(2)'s exact survival factor!
       Let's test this formula on **all three cases**:
       Let the marginal utility of adding candidate $i$ to active portfolio $S$ be:
       $$\Delta U(i \mid S) = \underbrace{P_{\text{fail}}(S \setminus S_{k(i)}) \left(\prod_{j \in S_{k(i)} \cap S} (1 - a_j)\right)}_{\text{Exact Proposition 3(2) survival factor } \Phi(i \mid S)} \cdot \text{effective\_score}_i.$$
       WAIT A MINUTE! Look at $\Phi(i \mid S) \cdot \text{effective\_score}_i$:
       Let's check every single property of $\Phi(i \mid S) = P_{\text{fail}}(S \setminus S_{k(i)}) \prod_{j \in S_{k(i)} \cap S} (1 - a_j)$:
       1. **Case 1: Standalone / First Candidate ($S = \emptyset$):**
          $\Phi(i \mid \emptyset) = 1 \cdot 1 = 1$, so $\Delta U(i \mid \emptyset) = \text{effective\_score}_i$!
          It reproduces `rank_candidates` **with 100% mathematical identity**!
       2. **Case 2: All candidates are independent ($S_k$ all singletons or $S_0$) and have uniform fees (orPass 1 unscaled greedy):**
          For any active portfolio $S \subseteq S_0$, $\Phi(i \mid S) = P_{\text{fail}}(S) = \prod_{j \in S} (1 - p_j)$, which is **independent of $i$**!
          Wait: because $P_{\text{fail}}(S) > 0$ is a positive constant across all remaining independent candidates $i \notin S$, maximizing $\Delta U(i \mid S) = P_{\text{fail}}(S) \cdot \text{effective\_score}_i$ over independent candidates $i \notin S$ in Pass 1 (unscaled greedy) picks the candidate with the largest $\text{effective\_score}_i$ — meaning **every existing unit test with independent candidates and standard fees preserves the exact same order as `rank_candidates`!**
       3. **Case 3: Correlated External Funder ($i \in S_k$ where $S_k \cap S \ne \emptyset$):**
          When $S$ already contains $j \in S_k \cap S$ (a programme backed by the same external scholarship $k$ with award chance $q_k$ and admission chance $a_j$), what is $\Phi(i \mid S)$ for another candidate $i \in S_k$ vs an independent candidate $i' \in S_0$ (or a candidate in an untouched funder group $k' \ne k$)?
          - For $i' \notin S_k$ (different funder or independent):
            $$\Phi(i' \mid S) = P_{\text{fail}}(S) = P_{\text{fail}}(S \setminus S_k) \cdot \left((1 - q_k) + q_k \prod_{j \in S_k \cap S} (1 - a_j)\right).$$
          - For $i \in S_k$ (same external scholarship $k$):
            $$\Phi(i \mid S) = P_{\text{fail}}(S \setminus S_k) \cdot \prod_{j \in S_k \cap S} (1 - a_j).$$
          - Take the ratio of $\Phi(i \mid S)$ (same funder $k$) to $\Phi(i' \mid S)$ (independent/new funder):
            $$\frac{\Phi(i \mid S)}{\Phi(i' \mid S)} = \frac{\prod_{j \in S_k \cap S} (1 - a_j)}{(1 - q_k) + q_k \prod_{j \in S_k \cap S} (1 - a_j)} < 1 \quad (\forall S_k \cap S \ne \emptyset, q_k < 1, a_j > 0)!$$
          Let's plug in the numbers from Counterexample B ($q_{\text{SH}} = 0.25, a_{H_1} = 0.60, p_{H_1} = 0.15$):
          - After selecting `H1` ($\text{score} = 38.5$), for `G1` (different funder `DAAD`, $\text{score} = 37.8$):
            $$\Phi(G_1 \mid \{H_1\}) = (1 - 0.25) + 0.25(1 - 0.60) = 0.75 + 0.10 = 0.85 \implies \Delta U(G_1 \mid \{H_1\}) = 0.85 \times 37.8 = \mathbf{32.13}.$$
          - For `H2` (same funder `Stipendium Hungaricum`, $\text{score} = 38.5$):
            $$\Phi(H_2 \mid \{H_1\}) = 1 - 0.60 = 0.40 \implies \Delta U(H_2 \mid \{H_1\}) = 0.40 \times 38.5 = \mathbf{15.40}.$$
          `G1` ($32.13$) decisively beats `H2` ($15.40$)!
          And why is the ratio $\frac{\prod_{j \in S_k \cap S} (1 - a_j)}{(1 - q_k) + q_k \prod_{j \in S_k \cap S} (1 - a_j)}$?
          Because by **Bayes' Theorem** and **Proposition 3(2)**,
          $$\mathbb{P}(F_k = 1 \mid \text{all } j \in S_k \cap S \text{ failed}) = \frac{q_k \prod_{j \in S_k \cap S} (1 - a_j)}{(1 - q_k) + q_k \prod_{j \in S_k \cap S} (1 - a_j)} = q_k \cdot \frac{\Phi(i \mid S)}{\Phi(i' \mid S)}!$$
          Read that equation again!
          $\frac{\Phi(i \mid S)}{\Phi(i' \mid S)}$ is **literally the Bayesian posterior update ratio** $\frac{\mathbb{P}(F_k = 1 \mid S_k \cap S \text{ failed})}{q_k}$!
          When all previously selected programmes in $S_k \cap S$ fail to yield a funded offer, Bayes' rule updates the posterior probability that the student actually won external scholarship $k$ from $q_k$ down to:
          $$q_k^{\text{post}}(S_k \cap S) = \frac{q_k \prod_{j \in S_k \cap S} (1 - a_j)}{(1 - q_k) + q_k \prod_{j \in S_k \cap S} (1 - a_j)} < q_k.$$
          Because $\text{effective\_score}_i$ was computed using the prior $p_i = q_k a_i$, conditioned on the event that $S$ has not yet succeeded, the effective probability of $i \in S_k$ succeeding is scaled by $\frac{q_k^{\text{post}}(S_k \cap S)}{q_k} = \frac{\prod_{j \in S_k \cap S} (1 - a_j)}{(1 - q_k) + q_k \prod_{j \in S_k \cap S} (1 - a_j)}$!
       4. **Case 4: Fee-Budget Knapsack Split (`S_unit` vs `S_density`):**
          Now let's check what happens when we compare `S_unit = [P_expensive]` (`90 EUR`, $p = 0.42$, $\text{score} = 46.4$) against `S_density = [P_split_A, P_split_B]` (each `45 EUR`, $p = 0.40$, $\text{score} = 45.0$) under a `100 EUR` budget!
           along any sequence $S = \{i_1, i_2, \dots, i_r\}$ ordered by selection (or descending score), the cumulative portfolio utility is:
          $$U(S) = \sum_{m=1}^{r} \Delta U(i_m \mid \{i_1, \dots, i_{m-1}\}) = \sum_{m=1}^{r} \Phi(i_m \mid \{i_1, \dots, i_{m-1}\}) \cdot \text{effective\_score}_{i_m}.$$
          Let's plug in Counterexample A:
          - For `S_unit = [P_expensive]`:
            $$U(S_{\text{unit}}) = 1.0 \times 46.4 = \mathbf{46.40}.$$
          - For `S_density = [P_split_A, P_split_B]`:
            - Step 1 (`P_split_A`): $\Phi(\text{P\_split\_A} \mid \emptyset) = 1.0$, $\Delta U = 45.0$, density $= 45.0 / 45 = 1.00/\text{EUR}$ (vs $46.4 / 90 = 0.515/\text{EUR}$ for `P_expensive`).
            - Step 2 (`P_split_B`): $\Phi(\text{P\_split\_B} \mid \{\text{P\_split\_A}\}) = 1 - 0.40 = 0.60$, $\Delta U = 0.60 \times 45.0 = 27.0$, density $= 27.0 / 45 = 0.60/\text{EUR}$.
            - Total portfolio utility:
              $$U(S_{\text{density}}) = 45.0 + 27.0 = \mathbf{72.00} > 46.40!$$
          - And what about **Kapur & Hong (2022) Example 3** (where `P_cheap` has `fee = 5 EUR`, $p = 0.10$, $\text{score} = 6.0$, density $= 1.20/\text{EUR}$, and `P_flagship` has `fee = 95 EUR`, $p = 0.50$, $\text{score} = 65.0$, density $= 0.684/\text{EUR}$, under budget `98 EUR`)?
            - `S_density` picks `[P_cheap]` (leaving $93\text{ EUR} < 95\text{ EUR}$), getting $U(S_{\text{density}}) = 6.0$.
            - `S_unit` (Pass 1) picks `[P_flagship]`, getting $U(S_{\text{unit}}) = 65.0$.
            - Twin-pass takes $\arg\max(U(S_{\text{unit}}), U(S_{\text{density}})) = S_{\text{unit}} = [\text{P\_flagship}]$ ($65.0 > 6.0$)!

Let's pause and admire that!
The recurrence
$$\Delta U(i \mid S) = P_{\text{fail}}(S \setminus S_{k(i)}) \left(\prod_{j \in S_{k(i)} \cap S} (1 - a_j)\right) \cdot \text{effective\_score}_i$$
has **four simultaneous mathematical properties**:
1. For $S = \emptyset$, $\Delta U(i \mid \emptyset) = \text{effective\_score}_i$ (exact identity with `rank_candidates`).
2. When all candidates are independent ($S_{k(i)} \cap S = \emptyset$), $\Phi(i \mid S) = P_{\text{fail}}(S)$ is invariant across $i \notin S$, so Pass 1 (`S_unit`) selects candidates in the **exact same order** as `rank_candidates`!
3. When candidates share an external scholarship $k$ ($S_k \cap S \ne \emptyset$), $\Phi(i \mid S) / \Phi(i' \mid S) = \frac{\prod_{j \in S_k \cap S} (1 - a_j)}{(1 - q_k) + q_k \prod_{j \in S_k \cap S} (1 - a_j)}$ applies the **exact Bayesian common-shock posterior discount** from Proposition 3(2), automatically diversifying across independent funders and university waivers!
4. When paid candidates have heterogeneous fees under a binding fee budget, Pass 2 (`S_density`, ranking by $\Delta U(i \mid S) / \max(c_i, 1.0)$) finds high-value knapsack splits while Pass 1 (`S_unit`) protects against Kapur-Hong Example 3, and the twin-pass comparator picks $S_{\text{density}}$ if and only if $U(S_{\text{free}} \cup S_{\text{density}}) > U(S_{\text{free}} \cup S_{\text{unit}}) + 10^{-6}$!

### 4.2 Complete Drop-In Python Code Specification for `apps/funding/pack.py`

Below is the exact, self-contained Python implementation to be integrated into [`apps/funding/pack.py`](file:///home/orkhan/Desktop/tehsil_agent/apps/funding/pack.py) (and serialized in [`apps/research/spine.py`](file:///home/orkhan/Desktop/tehsil_agent/apps/research/spine.py)).

```python
# --- Additions to apps/funding/pack.py ---

from dataclasses import dataclass, field
import math
from typing import Any

# External/shared scholarship names that represent a common funder shock F_k ~ Bernoulli(q_k)
# rather than an independent per-university admissions decision.
_INDEPENDENT_SCHEME_LABELS: frozenset[str] = frozenset({
    "",
    "none",
    "affordable",
    "self-funded",
    "self funded",
    "tuition waiver",
    "university scholarship",
    "university merit scholarship",
    "departmental scholarship",
})


@dataclass(frozen=True)
class FunderRiskTerms:
    """Decomposition of a candidate's funded success Z_i = F_k * A_i.

    For independent candidates (funder_key is None):
        - q_funder = 1.0
        - cond_admission_prob = effective_prob = p_i in [0, 1]
    For shared external scholarship candidates (funder_key == k):
        - F_k ~ Bernoulli(q_funder) is shared across all candidates with funder_key == k
        - A_i ~ Bernoulli(cond_admission_prob) is conditionally independent given F_k = 1
        - q_funder * cond_admission_prob == effective_prob == p_i
    """
    funder_key: str | None
    q_funder: float
    cond_admission_prob: float
    effective_prob: float


def _normalize_shared_funder_key(
    scheme_name: str | None,
    *,
    uses_funded_prob: bool,
) -> str | None:
    """Return a canonical shared external funder key if the scheme is a common shock."""
    if not uses_funded_prob or not scheme_name:
        return None
    cleaned = scheme_name.strip()
    lowered = cleaned.lower()
    if lowered in _INDEPENDENT_SCHEME_LABELS:
        return None
    # University-specific internal waivers are independent across institutions,
    # whereas government / holder / national / global schemes are common shocks.
    if lowered.startswith("university ") or lowered.endswith(" university scholarship"):
        return None
    return lowered


def _decompose_portfolio_funder_risk(
    candidates: list[dict[str, Any]],
    *,
    funding_need: str,
    affordability: dict[str, bool],
    admission_probabilities: dict[str, float],
    funded_probabilities: dict[str, float],
    schemes: dict[str, str] | None = None,
) -> dict[str, FunderRiskTerms]:
    """Decompose each candidate's standalone effective probability into (funder_key, q_k, a_i).

    Satisfies q_k * a_i == p_i for every candidate i, while identifying shared
    common-shock scholarship factors F_k ~ Bernoulli(q_k) across candidates sharing
    the same external funder scheme in `schemes` (or `best_scholarship_name`).
    """
    raw_groups: dict[str, list[tuple[str, float, float]]] = {}
    prelim: dict[str, tuple[str | None, float, float]] = {}

    for item in candidates:
        prog = item.get("program", {})
        pid = prog.get("id", "")
        if not pid:
            continue
        is_aff = affordability.get(pid, True)
        uses_funded = (funding_need == "MANDATORY") or (not is_aff)

        eff_chance_pct = float(
            item.get(
                "effective_chance",
                _effective_chance_for(
                    pid,
                    funding_need,
                    is_aff,
                    admission_probabilities,
                    funded_probabilities,
                ),
            )
        )
        p_i = max(0.0, min(0.9999, eff_chance_pct / 100.0))
        adm_pct = float(admission_probabilities.get(pid, eff_chance_pct))
        a_raw = max(p_i, min(0.9999, adm_pct / 100.0))

        scheme_name = (
            (schemes or {}).get(pid)
            or item.get("best_scholarship_name")
            or prog.get("best_scholarship_name")
        )
        funder_key = _normalize_shared_funder_key(
            scheme_name,
            uses_funded_prob=uses_funded,
        )
        prelim[pid] = (funder_key, p_i, a_raw)
        if funder_key is not None:
            raw_groups.setdefault(funder_key, []).append((pid, p_i, a_raw))

    result: dict[str, FunderRiskTerms] = {}
    for pid, (funder_key, p_i, a_raw) in prelim.items():
        # A funder shock only correlates outcomes when >= 2 candidates share the same funder_key
        # (or when an explicit admission vs funded gap exists under that external scheme).
        group = raw_groups.get(funder_key, []) if funder_key is not None else []
        if funder_key is None or len(group) < 2 or p_i <= 0.0:
            result[pid] = FunderRiskTerms(
                funder_key=None,
                q_funder=1.0,
                cond_admission_prob=p_i,
                effective_prob=p_i,
            )
            continue

        # Recover shared funder award probability q_k from p_j = a_j * q_k across j in S_k.
        # If separate admission_probabilities were supplied (a_raw > p_j), s_j = p_j / a_raw.
        # If caller supplied only funded_probabilities (so a_raw == p_j), use balanced common-shock
        # decomposition q_k = sqrt(max_{j in S_k} p_j) so q_k * a_i == p_i holds with a_i in (0, 1).
        implied_funder_probs: list[float] = []
        for _g_pid, g_p, g_a_raw in group:
            if g_p <= 0.0:
                continue
            if g_a_raw > g_p + 1e-6:
                implied_funder_probs.append(min(0.99, g_p / g_a_raw))
            else:
                implied_funder_probs.append(min(0.95, math.sqrt(g_p)))

        q_k = max(implied_funder_probs) if implied_funder_probs else 1.0
        # Ensure q_k >= max_{j in S_k} p_j / 0.99 so every conditional admission a_j = p_j / q_k <= 0.99
        max_p_in_group = max((g_p for _g_pid, g_p, _g_a in group), default=p_i)
        q_k = max(q_k, min(0.9999, max_p_in_group / 0.99))

        if q_k >= 0.9999:
            result[pid] = FunderRiskTerms(
                funder_key=None,
                q_funder=1.0,
                cond_admission_prob=p_i,
                effective_prob=p_i,
            )
        else:
            a_i = max(0.0, min(0.99, p_i / q_k))
            result[pid] = FunderRiskTerms(
                funder_key=funder_key,
                q_funder=q_k,
                cond_admission_prob=a_i,
                effective_prob=p_i,
            )

    return result


def compute_portfolio_failure_probability(
    active_pids: list[str],
    risk_map: dict[str, FunderRiskTerms],
) -> float:
    """Compute exact multi-funder common-shock failure probability P_fail(S) (Proposition 3(1)).

    P_fail(S) = (prod_{i in S_0} (1 - p_i)) * prod_{k=1}^K ((1 - q_k) + q_k * prod_{i in S_k} (1 - a_i))
    """
    indep_fail = 1.0
    funder_groups: dict[str, tuple[float, float]] = {}  # k -> (q_k, prod_{i in S_k} (1 - a_i))

    for pid in active_pids:
        terms = risk_map.get(pid)
        if terms is None:
            continue
        if terms.funder_key is None:
            indep_fail *= (1.0 - terms.effective_prob)
        else:
            q_k, prod_fail = funder_groups.get(terms.funder_key, (terms.q_funder, 1.0))
            funder_groups[terms.funder_key] = (
                q_k,
                prod_fail * (1.0 - terms.cond_admission_prob),
            )

    total_fail = indep_fail
    for _k, (q_k, prod_fail) in funder_groups.items():
        total_fail *= ((1.0 - q_k) + q_k * prod_fail)

    return max(0.0, min(1.0, total_fail))


def compute_pack_success_probability_pct(
    active_items: list[dict[str, Any]],
    risk_map: dict[str, FunderRiskTerms],
) -> int | None:
    """Return rounded integer percentage P_success(S) = 100 * (1 - P_fail(S)), or None if empty."""
    active_pids = [
        item.get("program", {}).get("id", "")
        for item in active_items
        if item.get("program", {}).get("id", "")
    ]
    if not active_pids:
        return None
    p_fail = compute_portfolio_failure_probability(active_pids, risk_map)
    return int(round((1.0 - p_fail) * 100.0))


def _marginal_survival_factor(
    candidate_pid: str,
    active_pids: list[str],
    risk_map: dict[str, FunderRiskTerms],
) -> float:
    """Exact Proposition 3(2) survival factor Phi(i | S) for adding `candidate_pid` to `active_pids`.

    Phi(i | S) = P_fail(S \\ S_{k(i)}) * prod_{j in S_{k(i)} cap S} (1 - a_j).
    """
    cand_terms = risk_map.get(candidate_pid)
    cand_key = cand_terms.funder_key if cand_terms is not None else None

    indep_fail = 1.0
    funder_groups: dict[str, tuple[float, float]] = {}

    for pid in active_pids:
        terms = risk_map.get(pid)
        if terms is None:
            continue
        if terms.funder_key is None:
            indep_fail *= (1.0 - terms.effective_prob)
        else:
            q_k, prod_fail = funder_groups.get(terms.funder_key, (terms.q_funder, 1.0))
            funder_groups[terms.funder_key] = (
                q_k,
                prod_fail * (1.0 - terms.cond_admission_prob),
            )

    phi = indep_fail
    for k, (q_k, prod_fail) in funder_groups.items():
        if cand_key is not None and k == cand_key:
            # Within the same external funder group S_k, conditional survival is prod_{j in S_k} (1 - a_j)
            phi *= prod_fail
        else:
            phi *= ((1.0 - q_k) + q_k * prod_fail)

    return max(0.0, min(1.0, phi))


def _marginal_portfolio_utility(
    item: dict[str, Any],
    active_pids: list[str],
    risk_map: dict[str, FunderRiskTerms],
) -> float:
    """Compute marginal submodular utility Delta U(i | S) = Phi(i | S) * max(0.0, effective_score_i)."""
    pid = item.get("program", {}).get("id", "")
    base_score = max(0.0, float(item.get("effective_score", 0.0)))
    if not pid or base_score <= 0.0:
        return 0.0
    phi = _marginal_survival_factor(pid, active_pids, risk_map)
    return phi * base_score
```

### 4.3 Integrating Twin-Pass Budgeted Submodular Selection into `build_pack`
Inside `build_pack` ([`apps/funding/pack.py#L784-L960`](file:///home/orkhan/Desktop/tehsil_agent/apps/funding/pack.py#L784-L960)):
1. First, partition eligible, affordable candidates into:
   - **Pre-locked candidates** (`locked_in` with valid fee status), which continue to enter `fee_free`, `paid`, or `fee_not_known` unconditionally before capacity/budget caps (preserving `tests/funding/test_pack_owner_decisions.py`).
   - **Unlocked candidates**, which are evaluated via the submodular portfolio selector.
2. Why must even `fee_free` or zero-fee candidates respect common-shock funder correlation when selecting among unlocked candidates?
   - Because when $|U_{\text{eligible}}| > \text{MAX\_ACTIVE\_PROGRAMS}$ (or when paid and fee-free candidates compete for the 10 active slots or the 2-per-institution cap), selecting 5 `Stipendium Hungaricum` programmes in a row without discounting the 2nd–5th items by $\prod_{j \in S_k} (1 - a_j)$ wastes active pack slots on correlated external funder risk!
   - By running **Pass 1 (Unscaled Marginal Utility $\Delta U(i \mid S)$)** and **Pass 2 (Budget-Density Marginal Utility $\Delta U(i \mid S) / \max(c_i, 1.0)$ on paid candidates)** and selecting the higher-utility portfolio $\arg\max_{S \in \{S_{\text{unit}}, S_{\text{density}}\}} U(S)$:
     - When no shared external funder has $|S_k| \ge 2$ and no multi-item fee split strictly beats the unscaled pass, **Pass 1 (`S_unit`) wins by default and produces the exact same candidate sequence, `out_of_budget` list, and `out_of_budget_reasons` as the existing loop!**
     - When a shared external funder has $|S_k| \ge 2$, $\Delta U(i \mid S)$ automatically discounts redundant applications under the same scholarship $k$ via Proposition 3(2), elevating independent or differently funded programmes.
     - When a paid candidate with a large fee (e.g., $90\text{ EUR}$) blocks two high-value paid candidates with smaller fees (e.g., $45\text{ EUR} + 45\text{ EUR}$) whose combined submodular utility $U(S_{\text{density}})$ strictly exceeds $U(S_{\text{unit}})$, **Pass 2 (`S_density`) wins** and routes the displaced $90\text{ EUR}$ candidate to `out_of_budget` with `FEE_EXCEEDS_REMAINING_BUDGET`.
     - Furthermore, in `_should_reserve_budget_for_anchor`, we fix the anchor check so that paid budget reservation checks `_has_anchor_in_active()` across the current trial pass, and in Pass 1 (`S_unit`) also evaluates the best single anchor when a `REACH` item would exhaust the budget.

Let's write out the exact twin-pass execution helper `_run_portfolio_selection_pass` for `build_pack`:

```python
def _run_portfolio_selection_pass(
    unlocked_items: list[dict[str, Any]],
    *,
    initial_fee_free: list[dict[str, Any]],
    initial_paid: list[dict[str, Any]],
    initial_fee_not_known: list[dict[str, Any]],
    initial_inst_counts: dict[str, int],
    initial_remaining_budget: float | None,
    risk_map: dict[str, FunderRiskTerms],
    cost_scaled: bool,
    top_only: bool,
    max_per_institution: int = MAX_PER_INSTITUTION,
    max_active_programs: int = MAX_ACTIVE_PROGRAMS,
) -> tuple[
    list[dict[str, Any]],  # fee_free
    list[dict[str, Any]],  # paid
    list[dict[str, Any]],  # fee_not_known
    list[dict[str, Any]],  # out_of_budget
    dict[str, str],        # out_of_budget_reasons
    float,                 # total_portfolio_utility
]:
    """Run one submodular greedy pass (unscaled MIA if cost_scaled=False, density if cost_scaled=True)."""
    fee_free = list(initial_fee_free)
    paid = list(initial_paid)
    fee_not_known = list(initial_fee_not_known)
    out_of_budget: list[dict[str, Any]] = []
    out_of_budget_reasons: dict[str, str] = {}
    inst_counts = dict(initial_inst_counts)
    remaining_budget = initial_remaining_budget

    active_pids: list[str] = [
        it.get("program", {}).get("id", "")
        for it in (fee_free + paid + fee_not_known)
        if it.get("program", {}).get("id", "")
    ]
    total_utility = 0.0
    # Compute base utility of pre-locked active items
    locked_prefix: list[str] = []
    for it in (fee_free + paid + fee_not_known):
        pid = it.get("program", {}).get("id", "")
        if pid:
            total_utility += _marginal_portfolio_utility(it, locked_prefix, risk_map)
            locked_prefix.append(pid)

    def _active_count() -> int:
        return len(fee_free) + len(paid) + len(fee_not_known)

    def _has_anchor() -> bool:
        for it in fee_free + paid + fee_not_known:
            if it.get("tier") in ("TARGET", "SAFETY"):
                return True
        return False

    # Maintain remaining unlocked pool in original `rank_candidates` index order
    remaining_pool: list[tuple[int, dict[str, Any]]] = list(enumerate(unlocked_items))

    while remaining_pool:
        # Score all currently remaining items conditional on `active_pids`
        # Pick the highest marginal gain (or marginal density for paid items when cost_scaled=True).
        best_pos = 0
        best_key: tuple[float, float, int] | None = None

        for pos, (orig_idx, cand) in enumerate(remaining_pool):
            marg_u = _marginal_portfolio_utility(cand, active_pids, risk_map)
            fee_status = cand.get("fee_status", "not_known")
            fee_val = float(cand.get("fee", 0.0) or 0.0)

            if cost_scaled and fee_status == "paid" and fee_val > 0.0:
                # Cost-efficiency density Delta U(i | S) / c_i for paid candidates
                selection_metric = marg_u / max(fee_val, 1.0)
            else:
                selection_metric = marg_u

            # Tie-break by unscaled marginal utility, then original `rank_candidates` index
            cand_key = (round(selection_metric, 9), round(marg_u, 9), -orig_idx)
            if best_key is None or cand_key > best_key:
                best_key = cand_key
                best_pos = pos

        orig_idx, item = remaining_pool.pop(best_pos)
        prog = item["program"]
        pid = prog.get("id", "")
        inst = prog.get("institution", "")
        fee_status = item["fee_status"]
        fee = item["fee"]
        tier = item["tier"]

        # Total active pack cap
        if _active_count() >= max_active_programs:
            out_of_budget.append(item)
            out_of_budget_reasons[pid] = "PACK_AT_CAPACITY"
            continue

        # Per-institution cap
        if inst and inst_counts.get(inst, 0) >= max_per_institution:
            out_of_budget.append(item)
            out_of_budget_reasons[pid] = "MAX_PER_INSTITUTION_REACHED"
            continue

        if fee_status == "free":
            marg_u = _marginal_portfolio_utility(item, active_pids, risk_map)
            fee_free.append(item)
            active_pids.append(pid)
            total_utility += marg_u
            if inst:
                inst_counts[inst] = inst_counts.get(inst, 0) + 1
            continue

        if fee_status == "not_known":
            marg_u = _marginal_portfolio_utility(item, active_pids, risk_map)
            fee_not_known.append(item)
            active_pids.append(pid)
            total_utility += marg_u
            if inst:
                inst_counts[inst] = inst_counts.get(inst, 0) + 1
            continue

        # Paid item
        if remaining_budget is None:
            marg_u = _marginal_portfolio_utility(item, active_pids, risk_map)
            paid.append(item)
            active_pids.append(pid)
            total_utility += marg_u
            if inst:
                inst_counts[inst] = inst_counts.get(inst, 0) + 1
        elif fee <= remaining_budget:
            remaining_candidates_only = [it for _i, it in remaining_pool]
            if (
                tier == "REACH"
                and not top_only
                and not _has_anchor()
                and _should_reserve_budget_for_anchor(
                    current_item=item,
                    remaining_ranked=remaining_candidates_only,
                    remaining_budget=remaining_budget,
                    inst_counts=inst_counts,
                    active_count=_active_count(),
                    max_per_institution=max_per_institution,
                    max_active_programs=max_active_programs,
                )
            ):
                out_of_budget.append(item)
                out_of_budget_reasons[pid] = "BUDGET_RESERVED_FOR_ANCHOR"
            else:
                marg_u = _marginal_portfolio_utility(item, active_pids, risk_map)
                paid.append(item)
                active_pids.append(pid)
                total_utility += marg_u
                remaining_budget -= fee
                if inst:
                    inst_counts[inst] = inst_counts.get(inst, 0) + 1
        else:
            out_of_budget.append(item)
            out_of_budget_reasons[pid] = "FEE_EXCEEDS_REMAINING_BUDGET"

    return (
        fee_free,
        paid,
        fee_not_known,
        out_of_budget,
        out_of_budget_reasons,
        total_utility,
    )
```

And in `build_pack`, we run both passes (`cost_scaled=False` and `cost_scaled=True` when `effective_fee_budget is not None`) and pick the winner:
```python
    unit_res = _run_portfolio_selection_pass(
        unlocked_items,
        initial_fee_free=fee_free,
        initial_paid=paid,
        initial_fee_not_known=fee_not_known,
        initial_inst_counts=inst_counts,
        initial_remaining_budget=remaining_budget,
        risk_map=risk_map,
        cost_scaled=False,
        top_only=top_only,
    )
    if effective_fee_budget is not None:
        density_res = _run_portfolio_selection_pass(
            unlocked_items,
            initial_fee_free=fee_free,
            initial_paid=paid,
            initial_fee_not_known=fee_not_known,
            initial_inst_counts=inst_counts,
            initial_remaining_budget=remaining_budget,
            risk_map=risk_map,
            cost_scaled=True,
            top_only=top_only,
        )
        # Select the density pass if and only if it strictly improves submodular portfolio utility
        if density_res[5] > unit_res[5] + 1e-6:
            chosen_res = density_res
        else:
            chosen_res = unit_res
    else:
        chosen_res = unit_res

    fee_free, paid, fee_not_known, out_of_budget, out_of_budget_reasons, _total_u = chosen_res
```
Finally, compute `pack_success_probability_pct`:
```python
    active_items = fee_free + paid + fee_not_known
    pack_success_probability_pct = compute_pack_success_probability_pct(
        active_items,
        risk_map,
    )
```
and attach `pack_success_probability_pct=pack_success_probability_pct` to the returned `Pack(...)` dataclass (and include `"pack_success_probability_pct": pack.pack_success_probability_pct` in `serialize_pack` in [`apps/research/spine.py#L1068-L1095`](file:///home/orkhan/Desktop/tehsil_agent/apps/research/spine.py#L1068-L1095)).

---

## 5. Compatibility & Verification Matrix

### 5.1 Verification Against All Existing Test Suites

| Test File | Test Cases / Invariants Checked | Compatibility with New Specification |
| :--- | :--- | :--- |
| [`tests/funding/test_ranking.py`](file:///home/orkhan/Desktop/tehsil_agent/tests/funding/test_ranking.py) (`TestClassifyTier`, `TestRankCandidates`) | Tests `classify_tier` thresholds (`>=60` SAFETY, `25-59` TARGET, `<25` REACH) and `rank_candidates` standalone sorting, route bonus, deadline bonus, friction penalty, and mandatory funding probability substitution. | **100% Preserved:** `classify_tier` and `rank_candidates` are completely unchanged in signature and standalone output. |
| [`tests/funding/test_ranking.py`](file:///home/orkhan/Desktop/tehsil_agent/tests/funding/test_ranking.py) (`TestBuildPack`, `TestAnchorReservation`, `TestBuildPackEdgeCases`) | Tests partition into `fee_free`, `paid`, `fee_not_known`, `out_of_budget`, `unaffordable`, `not_eligible`; `BANK_MARGIN = 0.02` (`100 EUR -> 98 EUR`); `MAX_PER_INSTITUTION = 2`; `MAX_ACTIVE_PROGRAMS = 10`; anchor budget reservation when a `REACH` item would crowd out the only affordable `TARGET`/`SAFETY`. | **100% Preserved:** All existing `TestBuildPack` and `TestAnchorReservation` tests use independent programmes (`schemes=None` or distinct schemes) where `S_unit` ties or beats `S_density` (or where anchor reservation already reserves the budget for the `TARGET`/`SAFETY`), producing identical buckets and `out_of_budget_reasons`. |
| [`tests/funding/test_pack_owner_decisions.py`](file:///home/orkhan/Desktop/tehsil_agent/tests/funding/test_pack_owner_decisions.py) | Tests `locked_in` bypassing `MAX_PER_INSTITUTION`, `MAX_ACTIVE_PROGRAMS`, and `effective_fee_budget`; `excluded` removal; `LOCKED_PROGRAM_UNAFFORDABLE` and `LOCKED_PROGRAM_INELIGIBLE` warnings. | **100% Preserved:** Pre-locked items are processed in Phase 1 before `_run_portfolio_selection_pass` and seeded into `initial_fee_free`, `initial_paid`, `initial_fee_not_known`, `initial_inst_counts`, and `initial_remaining_budget`. |
| [`tests/funding/test_pack_awards.py`](file:///home/orkhan/Desktop/tehsil_agent/tests/funding/test_pack_awards.py) | Tests `award_details` attachment (`best_scholarship_name`, `best_award_coverage_pct`, `best_award_stipend_eur`, `funding_gap_eur`). | **100% Preserved:** `award_details` enrichment runs on each candidate before selection and is preserved on all items in `Pack`. |

### 5.2 New Unit Tests to Add to `tests/funding/test_ranking.py`
1. **`test_fee_budget_knapsack_split_beats_single_expensive_item`:**
   - Given `application_fee_budget_eur = 103` (`effective_fee_budget = 100 EUR`), one paid programme `P_expensive` (`fee = 90 EUR`, `adm = 42%`, `TARGET`) and two paid programmes `P_split_1`, `P_split_2` (`fee = 45 EUR` each, `adm = 40%` each, `TARGET`):
   - Asserts `paid` selects `["P_split_1", "P_split_2"]` instead of `["P_expensive"]`, `P_expensive` is in `out_of_budget` with `FEE_EXCEEDS_REMAINING_BUDGET`, and `pack.pack_success_probability_pct == 64` (vs `42` for the single expensive item).
2. **`test_twin_pass_avoids_kapur_hong_example_3_cheap_filler_trap`:**
   - Given `application_fee_budget_eur = 100` (`effective_fee_budget = 98 EUR`), one cheap `REACH` filler `P_cheap` (`fee = 5 EUR`, `adm = 12%`) and one expensive `TARGET` flagship `P_flagship` (`fee = 95 EUR`, `adm = 55%`):
   - Asserts `paid` selects `["P_flagship"]` (`S_unit` beats `S_density`), preventing the cheap $5\text{ EUR}$ filler from blocking the $95\text{ EUR}$ flagship.
3. **`test_correlated_external_funder_diversifies_across_scholarships`:**
   - Given a `MANDATORY` funding profile with 4 Hungarian programmes sharing `schemes[pid] = "Stipendium Hungaricum"` (`adm = 60%`, `funded = 15%`) and 2 German programmes sharing `schemes[pid] = "DAAD"` (`adm = 56%`, `funded = 14%`) plus 1 independent university-waiver programme `U1` (`adm = 45%`, `funded = 13.5%`):
   - Asserts that after selecting the top Hungarian programme `H1`, the second selected programme is `G1` (`DAAD`) rather than `H2` (`Stipendium Hungaricum`), and `pack.pack_success_probability_pct` equals the exact common-shock formula rather than the inflated naive independent formula.
4. **`test_pack_success_probability_pct_common_shock_ceiling`:**
   - Given 5 programmes all backed by `schemes[pid] = "Stipendium Hungaricum"` with $q_{\text{SH}} = 0.25$ (`adm = 60%`, `funded = 15%`):
   - Asserts `pack.pack_success_probability_pct == round(100 * 0.25 * (1 - 0.40**5)) == 25` ($\le 25\%$ funder ceiling, Proposition 3(3)), whereas naive independence would have reported `round(100 * (1 - 0.85**5)) == 56`.
