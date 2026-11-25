# MAUT Preference Polytope Barycenter Weight Inference & Conjunctive-Compensatory Fit Scoring

**Role**: Scilit Deep Researcher E — MAUT Preference Polytope Barycenter Weight Inference & Conjunctive-Compensatory Fit Scoring  
**Target Codebase**: `/home/orkhan/Desktop/tehsil_agent` (`apps/accounts/schemas.py`, `apps/accounts/consultation.py`, `apps/funding/evaluation.py`, `apps/funding/facts.py`)  
**Date**: 2026-11-03

---

## 1. Executive Summary & `scilit` Provenance

### 1.1 `scilit` Run Provenance
All literature retrieval, claim verification, and symbolic/numerical theorem proving in this specification were executed via `scilit`:

| Tool / Stage | Run ID / Step Artifact | Status & Verification Metrics |
|---|---|---|
| `scilit find` | `20261103T141636Z-0ccc07f3` ([`report.md`](file:///home/orkhan/.scilit/runs/20261103T141636Z-0ccc07f3/report.md)) | Consulted 309 papers, scored 60, accepted 22 (`relevance >= 2`); retrieved primary papers on Rank-Order Centroid (ROC), SMARTER, polyhedral conjoint estimation, and generalized power-mean aggregation. |
| `scilit ask` | `20261103T142112Z-fcfb0857` ([`report.md`](file:///home/orkhan/.scilit/runs/20261103T142112Z-fcfb0857/report.md)) | Consulted 292 papers, scored 60, accepted 22, read 8 full texts, verified 9 claims with MiniCheck (0.75–0.99) + LLM judge (`on_unsupported=remove`, 0 disputed claims). |
| `scilit prove` (Prop. 1 Refutation & Repair) | `task-25` ([`steps/25/output.txt`](file:///home/orkhan/.gemini/antigravity/brain/0826e222-41d2-41fd-9037-e35af4cbb34d/.system_generated/steps/25/output.txt)) & `task-71` ([`steps/71/output.txt`](file:///home/orkhan/.gemini/antigravity/brain/0826e222-41d2-41fd-9037-e35af4cbb34d/.system_generated/steps/71/output.txt)) | **`proved: true`**, `fuzz_verified: true` (20 random $(K, \epsilon)$ instances + LP oracle), `sympy_verified: true` (exact symbolic verification for $K=2\dots 6$), `non_vacuous: true`. Falsified Chebyshev minimax $L_2/L_1$ optimality for $K \ge 3$ (`max_L2(w_roc)=0.417055 > 0.347011`) and proved exact Fréchet/Bayes $L_2^2$ risk optimality under $\text{Dirichlet}(1,\dots,1)$ + Bauer extreme-vertex reduction. |
| `scilit prove` (Prop. 2 Power Mean $M_p$) | `task-29` ([`steps/29/output.txt`](file:///home/orkhan/.gemini/antigravity/brain/0826e222-41d2-41fd-9037-e35af4cbb34d/.system_generated/steps/29/output.txt)) | **`proved: true`**, `fuzz_verified: true` (25 random instances), `sympy_verified: true` (5 symbolic subgoals: $C^\infty$ gradient, diminishing MRS, Hessian NSD & Schur-Ostrowski concavity, KL-divergence monotonicity in $p$, and continuous limits at $p \to -\infty, 0, 1$), `non_vacuous: true`. |

### 1.2 Primary Literature & Citations

1. **Edwards, W., & Barron, F. H. (1994)**. "SMARTS and SMARTER: Improved Simple Methods for Multiattribute Utility Measurement." *Organizational Behavior and Human Decision Processes*, 60(3), 306–325. DOI: `10.1006/obhd.1994.1087`. (`scilit find` `20261103T141636Z-0ccc07f3`)
   - Introduces **SMARTER** (*Simple Multi-Attribute Rating Technique Extended to Ranking*) and **Rank-Order Centroid (ROC)** weights $w_k^{\text{ROC}} = \frac{1}{K} \sum_{j=k}^K \frac{1}{j}$ as the geometric centroid (barycenter) of the ordered simplex $\{w_1 \ge w_2 \ge \dots \ge w_K \ge 0, \sum_{k=1}^K w_k = 1\}$, avoiding cognitively brittle direct point-allocation sliders.
2. **Barron, F. H., & Barrett, B. E. (1996a)**. "Decision Quality Using Ranked Attribute Weights." *Management Science*, 42(11), 1515–1523. DOI: `10.1287/mnsc.42.11.1515`. (`scilit find` `20261103T141636Z-0ccc07f3`, `scilit ask` `20261103T142112Z-fcfb0857`, relevance 3, rerank 8.2814)
   - Proves that over the uniform (Dirichlet) prior on the ordered attribute-weight sub-simplex $\mathcal{P}_\pi$, the centroid $\mathbf{w}^{\text{ROC}} = \mathbb{E}[\mathbf{w} \mid \mathbf{w} \in \mathcal{P}_\pi]$ is the unique Bayes-optimal point estimator under squared Euclidean loss $\mathbb{E}[\|\mathbf{w} - \hat{\mathbf{w}}\|_2^2]$ and achieves $>98\%$ of the expected multi-attribute value of true cardinal weights in simulation benchmarks, outperforming Rank Sum (RS) and Rank Reciprocal (RR).
3. **Barron, F. H., & Barrett, B. E. (1996b)**. "The efficacy of SMARTER — Simple Multi-Attribute Rating Technique Extended to Ranking." *Acta Psychologica*, 93(1–3), 23–36. DOI: `10.1016/0001-6918(96)00010-8`. (`scilit find` `20261103T141636Z-0ccc07f3`)
   - Extends ROC to **weak orders (tied ranks)**: when attributes in index block $B = \{r, r+1, \dots, s\}$ are tied in priority ($w_{\pi(r)} = \dots = w_{\pi(s)}$), the barycenter of the resulting lower-dimensional face of the simplex assigns each tied attribute the average of the ROC weights across the block:
     $$w_{\pi(k)} = \frac{1}{|B|} \sum_{m \in B} w_m^{\text{ROC}}.$$
4. **Solymosi, T., & Dombi, J. (1986)** / **ullei (1992)**. "A method for determining the weights of criteria: The centralized weights." *European Journal of Operational Research*, 26(1), 35–41. DOI: `10.1016/0377-2217(86)90157-8`; "Implementation of the centroid method of Solymosi and Dombi", *EJOR* (1992), DOI: `10.1016/0377-2217(92)90339-b`. (`scilit find` `20261103T141636Z-0ccc07f3`, `scilit ask` `20261103T142112Z-fcfb0857`)
   - Generalizes ROC to arbitrary linear inequality constraints $\mathcal{P} = \{\mathbf{w} \in \Delta^{K-1} : A\mathbf{w} \ge \mathbf{b}\}$ (including non-zero lower bounds $w_k \ge \epsilon$ and ratio bounds) by computing the exact vertex average (barycenter) of the constrained preference polytope.
5. **Toubia, O., Simester, D. I., Hauser, J. R., & Dahan, E. (2003)**. "Fast Polyhedral Adaptive Conjoint Estimation." *Marketing Science*, 22(3), 273–303. DOI: `10.1287/mksc.22.3.273.17743`; and **Toubia, O., Hauser, J. R., & Simester, D. I. (2004)**. "Polyhedral Methods for Adaptive Choice-Based Conjoint Analysis." *Journal of Marketing Research*, 41(1), 116–131. DOI: `10.1509/jmkr.41.1.116.25082`. (`scilit find` `20261103T141636Z-0ccc07f3`)
   - Models each qualitative or categorical user response as cutting the simplex $\Delta^{K-1}$ by linear half-spaces, yielding a feasible **preference polytope** $\mathcal{P} \subset \Delta^{K-1}$, and estimates the user's partworth/weight vector via the interior center (analytic center or barycenter) of $\mathcal{P}$ shrunk toward a population prior.
6. **Sauré, D., & Vielma, J. P. (2019)**. "Ellipsoidal Methods for Adaptive Choice-Based Conjoint Analysis." *Operations Research*, 67(2), 315–338. DOI: `10.1287/opre.2018.1790`. (`scilit find` `20261103T141636Z-0ccc07f3`)
   - Establishes the formal duality between polyhedral centering on $\mathcal{P} \subset \Delta^{K-1}$ and Bayesian posterior mean estimation under a prior distribution over the simplex.
7. **Danielson, M., & Ekenberg, L. (2014 / 2016 / 2022)**. "Augmenting Ordinal Methods of Attribute Weight Approximation." *Decision Analysis*, 11(1), 21–26. DOI: `10.1287/deca.2013.0289`; "Weighting Under Ambiguous Preferences and Imprecise Differences in a Cardinal Rank Ordering Process." *Int. J. Computational Intelligence Systems*, 6(1), 2013, DOI: `10.1080/18756891.2014.853954`; "An Empirical Comparison of Rank-Based Surrogate Weights in Additive Multiattribute Decision Analysis." *Decision Analysis* (2016/2022). (`scilit ask` `20261103T142112Z-fcfb0857`, `pqac-0010`)
   - Demonstrates that pure ROC on $K \ge 6$ dimensions can over-concentrate weight on rank 1 while starving the lowest rank ($w_K = 1/K^2 \approx 0.0204$ for $K=7$), and solves this by combining ordinal rank centroids with a minimum floor $\epsilon > 0$ and cardinal/Dirichlet regularization toward a domain reference vector.
8. **Dujmović, J. J. (1974 / 2018)**. "Weighted Conjunctive and Disjunctive Means and Their Application in System Evaluation." *Journal of the University of Belgrade, ETF Series*, No. 483 (1974); *Soft Computing Evaluation Logic: The LSP Decision Method and Its Applications* (Wiley-IEEE Press, 2018); and **Grabisch, M., Marichal, J.-L., Mesiar, R., & Pap, E. (2009)**. *Aggregation Functions* (Cambridge University Press, DOI: `10.1017/CBO9781139644150`).
   - Formalizes the **Weighted Generalized Power Mean (Hölder / Hardy-Littlewood-Pólya Mean)**
     $$M_p(\mathbf{w}, \mathbf{s}) = \left(\sum_{i=1}^K w_i s_i^p\right)^{1/p} \quad (p \neq 0), \qquad M_0(\mathbf{w}, \mathbf{s}) = \prod_{i=1}^K s_i^{w_i}$$
     as the unique continuous, scale-invariant (1-homogeneous), $C^\infty$-smooth family of aggregation operators spanning pure conjunction ($\lim_{p \to -\infty} M_p = \min_i s_i$, "andness" $= 1$), partial conjunction / non-compensatory bottleneck sensitivity ($p < 1$, including harmonic $p=-1$, root-harmonic $p=-0.5$, and Cobb-Douglas geometric $p=0$), and full linear compensation ($p = 1$, arithmetic mean $\sum_i w_i s_i$).

---

## 2. Mathematical Proofs (`scilit prove` Verified)

### 2.1 Proposition 1: Generalized Floored Rank-Order Centroid ($\text{ROC}(\epsilon)$), Weak-Order Extension, and Dirichlet-Regularized Simplex Inference

#### Statement of Proposition 1 (`scilit prove` verified in `task-71`, [`steps/71/output.txt`](file:///home/orkhan/.gemini/antigravity/brain/0826e222-41d2-41fd-9037-e35af4cbb34d/.system_generated/steps/71/output.txt))
Let $K \ge 2$ and let $0 < \epsilon < 1/K$ be a strict minimum weight floor. For any permutation $\pi \in S_K$ (without loss of generality $\pi = \text{id}$), define the $\epsilon$-floored ordered sub-simplex:
$$\mathcal{P}_{\pi,\epsilon} = \left\{\mathbf{w} \in \mathbb{R}^K : w_1 \ge w_2 \ge \dots \ge w_K \ge \epsilon, \quad \sum_{k=1}^K w_k = 1\right\} \subset \Delta^{K-1}.$$
Then:
1. **Extreme Vertices & Unique Abel Barycentric Coordinates**: $\mathcal{P}_{\pi,\epsilon} = \text{conv}\left(\{\mathbf{v}^{(1)}, \dots, \mathbf{v}^{(K)}\}\right)$ is a $(K-1)$-dimensional simplex with $K$ affinely independent extreme vertices $\mathbf{v}^{(m)} \in \mathbb{R}^K$ ($m=1,\dots,K$) given by:
   $$v_k^{(m)} = \begin{cases} \epsilon + \dfrac{1 - K\epsilon}{m}, & 1 \le k \le m, \\[6pt] \epsilon, & m < k \le K, \end{cases}$$
   with $\det(V) = \frac{(1 - K\epsilon)^{K-1}}{K!} > 0$. Every $\mathbf{w} \in \mathcal{P}_{\pi,\epsilon}$ has unique non-negative barycentric coordinates $\boldsymbol{\lambda}(\mathbf{w}) \in \Delta^{K-1}$ ($\mathbf{w} = \sum_{m=1}^K \lambda_m(\mathbf{w}) \mathbf{v}^{(m)}$):
   $$\lambda_m(\mathbf{w}) = \frac{m(w_m - w_{m+1})}{1 - K\epsilon} \quad (1 \le m \le K-1), \qquad \lambda_K(\mathbf{w}) = \frac{K(w_K - \epsilon)}{1 - K\epsilon}.$$
2. **Closed-Form Barycenter ($\text{ROC}(\epsilon)$)**: The exact centroid (barycenter) of $\mathcal{P}_{\pi,\epsilon}$ under the uniform Lebesgue / $\text{Dirichlet}(1,\dots,1)$ measure is:
   $$w_k^{\text{ROC}(\epsilon)} = \frac{1}{K} \sum_{m=1}^K v_k^{(m)} = \epsilon + \frac{1 - K\epsilon}{K} \sum_{j=k}^K \frac{1}{j}, \qquad k = 1, \dots, K.$$
   It satisfies $\sum_{k=1}^K w_k^{\text{ROC}(\epsilon)} = 1$, strict adjacent separation $w_k^{\text{ROC}(\epsilon)} - w_{k+1}^{\text{ROC}(\epsilon)} = \frac{1 - K\epsilon}{K k} > 0$, and strict lower bound $w_K^{\text{ROC}(\epsilon)} = \epsilon + \frac{1 - K\epsilon}{K^2} > \epsilon > 0$.
3. **Exact Bayes $L_2^2$ Optimality (and Refutation of Chebyshev Minimax Optimality)**: For any candidate weight vector $\hat{\mathbf{w}} \in \mathbb{R}^K$, the expected squared Euclidean error under $\mathbf{w} \sim \text{Unif}(\mathcal{P}_{\pi,\epsilon})$ ($\boldsymbol{\lambda} \sim \text{Dirichlet}(1,\dots,1)$) and the discrete vertex MSE decompose exactly as:
   $$\mathbb{E}_{\mathbf{w} \sim \text{Unif}(\mathcal{P}_{\pi,\epsilon})}\left[\|\mathbf{w} - \hat{\mathbf{w}}\|_2^2\right] = \|\hat{\mathbf{w}} - \mathbf{w}^{\text{ROC}(\epsilon)}\|_2^2 + \frac{1}{K(K+1)} \sum_{m=1}^K \|\mathbf{v}^{(m)} - \mathbf{w}^{\text{ROC}(\epsilon)}\|_2^2,$$
   $$\frac{1}{K}\sum_{m=1}^K \|\mathbf{v}^{(m)} - \hat{\mathbf{w}}\|_2^2 = \|\hat{\mathbf{w}} - \mathbf{w}^{\text{ROC}(\epsilon)}\|_2^2 + \frac{1}{K}\sum_{m=1}^K \|\mathbf{v}^{(m)} - \mathbf{w}^{\text{ROC}(\epsilon)}\|_2^2.$$
   Hence $\hat{\mathbf{w}} = \mathbf{w}^{\text{ROC}(\epsilon)}$ is the unique Bayes-optimal estimator minimizing expected squared Euclidean error over $\mathcal{P}_{\pi,\epsilon}$. (By contrast, as falsified by `scilit prove` in `task-25` for $K=3, \epsilon=0.05$, $\max_{\mathbf{w} \in \mathcal{P}_{\pi,\epsilon}} \|\mathbf{w} - \mathbf{w}^{\text{ROC}(\epsilon)}\|_2 = 0.417055 > 0.347011$, because the centroid of an asymmetric simplex is distinct from its Chebyshev minimax center.)
4. **Bauer Extreme-Vertex Reduction for Worst-Case Linear Utility Error**: For any multi-attribute score vector $\mathbf{u} \in \mathbb{R}^K$, the worst-case linear utility discrepancy over $\mathcal{P}_{\pi,\epsilon}$ is attained at the $K$ extreme vertices:
   $$\max_{\mathbf{w} \in \mathcal{P}_{\pi,\epsilon}} \left|\mathbf{u}^\top (\mathbf{w} - \hat{\mathbf{w}})\right| = \max_{1 \le m \le K} \left|\mathbf{u}^\top (\mathbf{v}^{(m)} - \hat{\mathbf{w}})\right|.$$
5. **Weak-Order (Tied-Rank) Face Barycenter & Dirichlet Prior Shrinkage**: When the student's regime choices induce a weak order (total preorder) partitioning $\{1,\dots,K\}$ into ordered tie blocks $B_1 \succ B_2 \succ \dots \succ B_L$ where block $B_\ell$ occupies rank positions $\{r_\ell, r_\ell + 1, \dots, s_\ell\}$, the barycenter of the corresponding polyhedral face $\mathcal{P}_{\succeq,\epsilon} = \{\mathbf{w} \in \mathcal{P}_{\pi,\epsilon} : w_i = w_j \text{ for } i,j \in B_\ell\}$ is the block-averaged generalized ROC vector:
   $$w_i^{\text{WROC}(\epsilon)} = \frac{1}{|B_\ell|} \sum_{k=r_\ell}^{s_\ell} w_k^{\text{ROC}(\epsilon)} = \epsilon + \frac{1 - K\epsilon}{K |B_\ell|} \sum_{k=r_\ell}^{s_\ell} \sum_{j=k}^K \frac{1}{j}, \qquad \forall i \in B_\ell.$$
   In particular, when all $K$ dimensions are tied in a single block $B_1 = \{1,\dots,K\}$ ($L=1$), $w_i^{\text{WROC}(\epsilon)} = \frac{1}{K}$ for all $i$. Furthermore, under a Dirichlet conjugate prior $\mathbf{w} \sim \text{Dirichlet}(\tau_0 \mathbf{w}_0)$ anchored at the institutional baseline $\mathbf{w}_0 = \text{DEFAULT\_WEIGHTS} \in \Delta^{K-1}$ updated with pseudo-count concentration $\tau_{\text{sal}} \ge 0$ aligned with $\mathbf{w}^{\text{WROC}(\epsilon)}$, the posterior mean is the convex combination:
   $$\mathbf{w}^*(\lambda) = (1 - \lambda)\mathbf{w}_0 + \lambda \mathbf{w}^{\text{WROC}(\epsilon)} \in \Delta^{K-1}, \qquad \lambda = \frac{\tau_{\text{sal}}}{\tau_0 + \tau_{\text{sal}}} \in [0, 1),$$
   which satisfies $\mathbf{w}^*(0) = \mathbf{w}_0 = \text{DEFAULT\_WEIGHTS}$ whenever no differentiating regime signal is active ($\tau_{\text{sal}} = 0$), and $w_i^*(\lambda) \ge (1 - \lambda)\min_k w_{0,k} + \lambda \epsilon > 0$ for all $i$.

---

### 2.2 Proposition 2: Smooth Conjunctive-Compensatory Aggregation via Weighted Generalized Power Mean $M_p(\mathbf{w}, \mathbf{s})$

#### Statement of Proposition 2 (`scilit prove` verified in `task-29`, [`steps/29/output.txt`](file:///home/orkhan/.gemini/antigravity/brain/0826e222-41d2-41fd-9037-e35af4cbb34d/.system_generated/steps/29/output.txt))
Let $\mathbf{w} = (w_1, \dots, w_K) \in \Delta^{K-1}$ have strictly positive weights $w_i > 0$ ($\sum_{i=1}^K w_i = 1$), and let $\mathbf{s} = (s_1, \dots, s_K) \in [\delta, 100]^K$ with $\delta > 0$ (e.g., $\delta = 1$). For $p \in \mathbb{R}$, define the weighted generalized power mean (Hölder mean):
$$M_p(\mathbf{w}, \mathbf{s}) = \begin{cases} \left(\displaystyle\sum_{i=1}^K w_i s_i^p\right)^{1/p}, & p \neq 0, \\[10pt] \displaystyle\prod_{i=1}^K s_i^{w_i} = \exp\left(\sum_{i=1}^K w_i \ln s_i\right), & p = 0. \end{cases}$$
Then:
1. **$C^\infty$-Smoothness and Strict Monotonicity**: $M_p(\mathbf{w}, \cdot)$ is $C^\infty$-smooth on $[\delta, 100]^K$ (eliminating step-function threshold cliffs) and strictly increasing in each attribute score $s_i$:
   $$\frac{\partial M_p(\mathbf{w}, \mathbf{s})}{\partial s_i} = w_i \left(\frac{s_i}{M_p(\mathbf{w}, \mathbf{s})}\right)^{p-1} > 0.$$
2. **Diminishing Marginal Rate of Substitution (Bottleneck Amplification for $p < 1$)**: For any pair of dimensions $(i, j)$, the marginal rate of substitution of dimension $j$ for dimension $i$ is:
   $$\text{MRS}_{i,j}(\mathbf{s}) = \frac{\partial M_p / \partial s_i}{\partial M_p / \partial s_j} = \frac{w_i}{w_j} \left(\frac{s_j}{s_i}\right)^{1-p}, \qquad \frac{\partial \text{MRS}_{i,j}}{\partial s_i} = -(1-p)\frac{w_i}{w_j} s_j^{1-p} s_i^{p-2} < 0 \quad (\forall p < 1).$$
   Thus, whenever $p < 1$ and $s_i < s_j$, the marginal sensitivity to improving the weak dimension $s_i$ is amplified by $(s_j / s_i)^{1-p} > 1$: a high score $s_j = 100$ in `AFFORDABILITY` cannot linearly mask a weak score $s_i = 50$ in `ACADEMIC_FIT` or `PROGRAM_FIT`.
3. **Joint Concavity & Strict Schur-Concavity**: For all $p < 1$, the Hessian matrix of $M_p$ on $\mathbb{R}_{++}^K$ is negative semi-definite:
   $$\nabla^2_{\mathbf{s}} M_p(\mathbf{w}, \mathbf{s}) = (p - 1) M_p(\mathbf{w}, \mathbf{s})^{1-p} \left(\text{Diag}\left(\frac{u_i}{s_i^2}\right) - \mathbf{q}\mathbf{q}^\top\right) \preceq 0, \qquad u_i = \frac{w_i s_i^p}{\sum_k w_k s_k^p}, \quad q_i = \frac{u_i}{s_i},$$
   and $M_p$ satisfies the strict Schur-Ostrowski condition $(s_i - s_j)\left(\frac{\partial M_p}{\partial s_i} - \frac{\partial M_p}{\partial s_j}\right) < 0$ (under equal weights whenever $s_i \neq s_j$), strictly preferring balanced profiles over lopsided profiles with the same arithmetic mean $M_1(\mathbf{w}, \mathbf{s})$.
4. **Monotonicity in $p$ via Kullback-Leibler Divergence**: For all $\mathbf{s} \in [\delta, 100]^K$,
   $$\frac{\partial}{\partial p} \ln M_p(\mathbf{w}, \mathbf{s}) = \frac{\text{KL}(\mathbf{u} \,\|\, \mathbf{w})}{p^2} = \frac{1}{p^2} \sum_{i=1}^K u_i \ln\left(\frac{u_i}{w_i}\right) \ge 0,$$
   so $M_{p_1}(\mathbf{w}, \mathbf{s}) \le M_{p_2}(\mathbf{w}, \mathbf{s})$ for all $p_1 < p_2$, with equality if and only if $s_1 = s_2 = \dots = s_K$.
5. **Exact Continuous Interpolation Across Decision Regimes**:
   $$\lim_{p \to -\infty} M_p(\mathbf{w}, \mathbf{s}) = \min_{1 \le i \le K} s_i, \qquad \lim_{p \to 0} M_p(\mathbf{w}, \mathbf{s}) = \prod_{i=1}^K s_i^{w_i}, \qquad M_1(\mathbf{w}, \mathbf{s}) = \sum_{i=1}^K w_i s_i.$$

---

## 3. Line-by-Line Codebase Audit

### 3.1 Summary of Audited Files and Identified Defects

| File & Lines | Current Implementation | Mathematical / Domain Defect | Required Fix |
|---|---|---|---|
| [`apps/accounts/schemas.py:117-139`](file:///home/orkhan/Desktop/tehsil_agent/apps/accounts/schemas.py#L117-L139) | `EvaluationDimension` ($K=7$) and `DEFAULT_WEIGHTS = MappingProxyType({"ACADEMIC_FIT": 0.20, "PROGRAM_FIT": 0.20, "CAREER_FIT": 0.15, "AFFORDABILITY": 0.20, "DURATION": 0.05, "MOBILITY_FIT": 0.10, "RESEARCH_FIT": 0.10})`. | Static constant dictionary; no function exists to map a student's categorical regime choices (`funding_dependency`, `career_intent`, `duration_preference`, `duration_flexibility`, `mobility_priorities`, `research_interests`) onto a personalized weight vector $\mathbf{w} \in \Delta^6$. | Add deterministic `infer_simplex_weights_from_profile(...) -> dict[EvaluationDimension, Decimal]` implementing Dirichlet-regularized Weak-Order $\text{ROC}(\epsilon)$ on $\Delta^6$ while returning `dict(DEFAULT_WEIGHTS)` when no differentiating signal is present. |
| [`apps/accounts/schemas.py:197-240`](file:///home/orkhan/Desktop/tehsil_agent/apps/accounts/schemas.py#L197-L240) | `StudentProfileSnapshot.weights` defaults to `Field(default_factory=lambda: DEFAULT_WEIGHTS)` and validates `total == Decimal("1")`. | Note: [`tests/accounts/test_profile_schema_v3.py:52`](file:///home/orkhan/Desktop/tehsil_agent/tests/accounts/test_profile_schema_v3.py#L52) directly calls `StudentProfileSnapshot.model_validate(_answers())` without `"weights"` and asserts `profile.weights == DEFAULT_WEIGHTS`. | Keep `StudentProfileSnapshot.weights` default factory as `DEFAULT_WEIGHTS` so direct schema instantiation preserves `test_profile_schema_v3.py:52`, and expose `infer_simplex_weights_from_profile(...)` for consultation payload construction (`_profile_payload`) and explicit callers. |
| [`apps/accounts/consultation.py:529-539`](file:///home/orkhan/Desktop/tehsil_agent/apps/accounts/consultation.py#L529-L539), [`649-745`](file:///home/orkhan/Desktop/tehsil_agent/apps/accounts/consultation.py#L649-L745) | `_DURATION_PREF_RE` only parses 1-year and 2-year durations; `_profile_payload(draft)` never sets `payload["weights"]`. | (1) 15–18 month (`1.5-year`, `18-month`, `3-semester`) preferences in `additional_notes` are ignored. (2) Every consultation profile gets static `DEFAULT_WEIGHTS` even when `funding_dependency="MANDATORY"`, `career_intent="PHD"`, or `duration_preference` is specified. | (1) Extend duration regex/enum to support `"ONE_AND_HALF_YEAR"` (15–18 months). (2) In `_profile_payload(draft)` and `finalize_consultation`, infer `payload["weights"] = infer_simplex_weights_from_profile(payload)` whenever regime signals differentiate dimensions (unless explicit custom weights were set). |
| [`apps/funding/evaluation.py:267-321`](file:///home/orkhan/Desktop/tehsil_agent/apps/funding/evaluation.py#L267-L321) | `duration_category(duration_months)` returns `"ONE_YEAR" if duration_months <= 12 else "TWO_YEAR"`. | Binary step at 12 months conflates 15–18 month European/professional Master's programmes (e.g., 90 ECTS / 16-month / 18-month MSc) with 24-month `TWO_YEAR` degrees. | Add `duration_band(duration_months: int) -> Literal["ONE_YEAR", "ONE_AND_HALF_YEAR", "TWO_YEAR"]` (`<= 14` $\to$ `"ONE_YEAR"`, `15..18` $\to$ `"ONE_AND_HALF_YEAR"`, `>= 19` $\to$ `"TWO_YEAR"`) while keeping backward compatibility for legacy `"ONE_YEAR"` / `"TWO_YEAR"` callers. |
| [`apps/funding/evaluation.py:517-553`](file:///home/orkhan/Desktop/tehsil_agent/apps/funding/evaluation.py#L517-L553), [`720-755`](file:///home/orkhan/Desktop/tehsil_agent/apps/funding/evaluation.py#L720-L755) | `score_dimensions` computes purely linear `overall = sum(d.score * d.weight)` ($p=1$ arithmetic mean), and `evaluate()` uses a step-function cliff `overall >= 80 and min(critical_values) >= 60`. | Complete compensability ($p=1$) lets `AFFORDABILITY=100` mask `ACADEMIC_FIT=60`; simultaneously, `min(critical_values) >= 60` creates a discontinuous cliff between `59.9` and `60.0`. | Add `power_mean_score(dimensions, p=...)` (weighted Hölder mean $M_p(\mathbf{w}, \mathbf{s})$ with $p < 1$, e.g. $p = -0.5$ for `BALANCED` / `TOP_TIER_ACADEMIC` and $p = -1.0$ for `FUNDING_FIRST`) and smooth conjunctive-compensatory fit evaluation. |
| [`apps/funding/facts.py:459-511`](file:///home/orkhan/Desktop/tehsil_agent/apps/funding/facts.py#L459-L511) | `score_program_fit` computes `ACADEMIC_FIT` only from field token overlap (`85` or `65`), teaching language (`+5`), and coursework statements (`only_coursework=True`). | **Completely ignores GPA/grades** (`record.grade`, `record.grading_scale`) and ignores GPA `ProgramStatement`s (`only_coursework=True` skips `statement.category == "GPA"`!). A student with a `2.1/4.0` GPA receives the exact same `ACADEMIC_FIT` as a `3.95/4.0` student. | Integrate Bavarian grade normalization (`_bavarian_from_record` from `transcript_eligibility.py`, where $1.0$ is best and $4.0$ is minimum pass) and GPA `ProgramStatement` / `RequirementRule` margin into `ACADEMIC_FIT` in `score_program_fit`. |
| [`apps/funding/facts.py:523-551`](file:///home/orkhan/Desktop/tehsil_agent/apps/funding/facts.py#L523-L551) | `DURATION` scoring in `score_program_fit` checks `category == pref` using the binary `ONE_YEAR` / `TWO_YEAR` split. | Under `ONE_YEAR` preference (`WEIGHTED` or `FLEXIBLE`), an 18-month programme is penalized identically (`65` or `40`) to a 24-month programme, and `ONE_AND_HALF_YEAR` preferences cannot be scored. | Score `DURATION` using continuous/banded month distance (`duration_band` + month deviation $|\text{duration\_months} - \text{target\_months}|$), awarding intermediate credit (`75`–`80`) to 15–18 month programmes when `ONE_YEAR` or `TWO_YEAR` is preferred. |

---

### 3.2 Detailed Audit by File

#### 1. [`apps/accounts/schemas.py`](file:///home/orkhan/Desktop/tehsil_agent/apps/accounts/schemas.py)
- **Lines 89–90**:
  ```python
  DurationPreference = Literal["ONE_YEAR", "TWO_YEAR", "NO_PREFERENCE"]
  DurationFlexibility = Literal["NON_NEGOTIABLE", "WEIGHTED", "FLEXIBLE"]
  ```
  `DurationPreference` lacks `"ONE_AND_HALF_YEAR"` for 15–18 month programmes (e.g., 3-semester / 90 ECTS European Master's or 16-month accelerated professional Master's).
- **Lines 117–139**:
  ```python
  EvaluationDimension = Literal[
      "ACADEMIC_FIT",
      "PROGRAM_FIT",
      "CAREER_FIT",
      "AFFORDABILITY",
      "DURATION",
      "MOBILITY_FIT",
      "RESEARCH_FIT",
  ]
  DEFAULT_WEIGHTS: Mapping[EvaluationDimension, Decimal] = MappingProxyType(
      {
          "ACADEMIC_FIT": Decimal("0.20"),
          "PROGRAM_FIT": Decimal("0.20"),
          "CAREER_FIT": Decimal("0.15"),
          "AFFORDABILITY": Decimal("0.20"),
          "DURATION": Decimal("0.05"),
          "MOBILITY_FIT": Decimal("0.10"),
          "RESEARCH_FIT": Decimal("0.10"),
      }
  )
  ```
  Every dimension has a fixed baseline weight regardless of student regime.
- **Lines 230–240**:
  `weights_are_probabilities` checks that `set(self.weights.keys()) == set( EVALUATION_DIMENSIONS )`, each $0 \le v \le 1$, and `sum(self.weights.values()) == Decimal("1")`. Any inferred simplex weight vector must therefore use exact `Decimal` quantization (`Decimal("0.0001")` or `Decimal("0.01")`) with largest-remainder residual adjustment so that `sum(weights.values()) == Decimal("1")` holds identically in `Decimal` arithmetic.

#### 2. [`apps/accounts/consultation.py`](file:///home/orkhan/Desktop/tehsil_agent/apps/accounts/consultation.py)
- **Lines 529–539 & 649–694**:
  `_DURATION_PREF_RE` matches `(?:one|1)\s*[-\s]?year|12\s*[-\s]?month` and `(?:two|2)\s*[-\s]?year|24\s*[-\s]?month`, missing `1.5-year`, `18-month`, `15-month`, `16-month`, `three-semester`, or `3-semester`.
- **Lines 696–745**:
  `_profile_payload(draft)` builds the dictionary validated by `StudentProfileSnapshot.model_validate(...)` but never populates `"weights"`.
- **Lines 1330–1345**:
  In `finalize_consultation`, if `prev_snap.get("weights")` exists on an earlier snapshot, it is copied verbatim (`payload["weights"] = prev_snap["weights"]`) even when the student's `career_intent`, `funding_dependency`, `duration_preference`, or `additional_notes` changed during re-consultation!

#### 3. [`apps/funding/evaluation.py`](file:///home/orkhan/Desktop/tehsil_agent/apps/funding/evaluation.py)
- **Lines 267–268**:
  ```python
  def duration_category(duration_months: int) -> Literal["ONE_YEAR", "TWO_YEAR"]:
      return "ONE_YEAR" if duration_months <= 12 else "TWO_YEAR"
  ```
- **Lines 470–506**:
  `applicable_dimensions(profile)` drops `DURATION` when `profile.duration_preference == "NO_PREFERENCE"`, drops `MOBILITY_FIT` when `not profile.mobility_priorities`, and drops `RESEARCH_FIT` when `profile.career_intent not in {"PHD", "ACADEMIA"}`. Then `redistribute_weights(weights, applicable)` scales the active weights by $1 / \sum_{d \in \mathcal{A}} w_d$ and adds the rounding residual to `max(scaled, key=lambda d: scaled[d])`.
- **Lines 517–553**:
  `score_dimensions(profile, candidate, affordability)` computes:
  ```python
  overall = sum((d.score * d.weight for d in dimensions), Decimal("0")).quantize(
      Decimal("0.01"), rounding=ROUND_HALF_UP
  )
  ```
  Because $p=1$, `overall` is 100% linearly compensatory.

#### 4. [`apps/funding/facts.py`](file:///home/orkhan/Desktop/tehsil_agent/apps/funding/facts.py)
- **Lines 459–511 (`score_program_fit` — `ACADEMIC_FIT`)**:
  ```python
  base_academic = Decimal("85") if prior_tokens & (target_tokens | program_tokens) else Decimal("65")
  lang_bonus = Decimal("5") if set(program.teaching_languages) & student_langs else Decimal("0")
  ...
  for stmt in statements:
      outcome = evaluate_program_statement(
          stmt, profile, student_certs, only_coursework=True
      )
  ```
  Notice two compounding bugs:
  1. `only_coursework=True` explicitly filters out `stmt.category == "GPA"` (see [`apps/funding/transcript_eligibility.py:5526`](file:///home/orkhan/Desktop/tehsil_agent/apps/funding/transcript_eligibility.py#L5526): `if only_coursework and statement.category != "COURSEWORK": return None`). So GPA statements on a programme are never evaluated in `ACADEMIC_FIT`!
  2. Even when a programme has no explicit GPA `ProgramStatement` or when the student exceeds the minimum GPA bar, `profile.academic_history` (`record.grade`, `record.grading_scale`) is never read in `score_program_fit`. Yet [`apps/funding/transcript_eligibility.py:4889-4903`](file:///home/orkhan/Desktop/tehsil_agent/apps/funding/transcript_eligibility.py#L4889-L4903) already provides `_bavarian_from_record(record)` which converts any student record (`GPA_4`, `PERCENTAGE_100`, `GPA_10`, `BAVARIAN`, `UK_HONOURS`, etc.) to the unified Bavarian scale $b \in [1.0, 4.0]$ (where $1.0$ = 100% / 4.0 US GPA and $4.0$ = minimum pass).
- **Lines 523–551 (`score_program_fit` — `DURATION`)**:
  Uses `category = duration_category(program.duration_months)` (`ONE_YEAR` vs `TWO_YEAR`). A 15–18 month programme (`program.duration_months in range(15, 19)`) is treated identically to a 24-month programme (`TWO_YEAR`), receiving `40` (when `duration_flexibility != "WEIGHTED"`) or `65` (when `WEIGHTED` without justification) under a `ONE_YEAR` preference.

---

## 4. Drop-In Python Algorithmic Specification

### 4.1 Part (a): Preference Polytope Barycenter & Dirichlet-Regularized Weight Inference (`apps/accounts/schemas.py` & `apps/accounts/consultation.py`)

#### Mathematical Construction of `infer_simplex_weights_from_profile`
1. **Dimension Space ($K = 7$)**:
   $$\mathcal{D} = (\text{ACADEMIC\_FIT}, \text{PROGRAM\_FIT}, \text{CAREER\_FIT}, \text{AFFORDABILITY}, \text{DURATION}, \text{MOBILITY\_FIT}, \text{RESEARCH\_FIT}).$$
2. **Baseline Prior Anchor ($\mathbf{w}_0 \in \Delta^6$)**:
   $$\mathbf{w}_0 = \text{DEFAULT\_WEIGHTS} = (0.20, 0.20, 0.15, 0.20, 0.05, 0.10, 0.10).$$
3. **Regime Salience Scoring ($S_d \in \mathbb{R}$)**:
   Each dimension $d \in \mathcal{D}$ starts at a baseline ordinal salience $S_d^{(0)}$ that induces the baseline weak order of `DEFAULT_WEIGHTS`:
   - Tier 1 ($S^{(0)} = 30$): `ACADEMIC_FIT`, `PROGRAM_FIT`, `AFFORDABILITY` ($w_0 = 0.20$)
   - Tier 2 ($S^{(0)} = 20$): `CAREER_FIT` ($w_0 = 0.15$)
   - Tier 3 ($S^{(0)} = 10$): `MOBILITY_FIT`, `RESEARCH_FIT` ($w_0 = 0.10$)
   - Tier 4 ($S^{(0)} = 0$): `DURATION` ($w_0 = 0.05$)

   Student regime choices add deterministic salience shifts $\Delta S_d$ derived from the profile fields:
   - **`funding_dependency`**:
     - `"MANDATORY"`: $\Delta S_{\text{AFFORDABILITY}} += 25$ (elevates `AFFORDABILITY` to top priority).
     - `"PREFERRED"`: $\Delta S_{\text{AFFORDABILITY}} += 10$.
     - `"OPTIONAL"` (or `"NO_FUNDING_NEEDED"` in `mobility_priorities`): $\Delta S_{\text{AFFORDABILITY}} -= 20$ (demotes `AFFORDABILITY` below academic/program/career fit).
   - **`career_intent`**:
     - `"PHD"` or `"ACADEMIA"`: $\Delta S_{\text{RESEARCH\_FIT}} += 25$, $\Delta S_{\text{ACADEMIC\_FIT}} += 10$ (elevates `RESEARCH_FIT` and `ACADEMIC_FIT` to top ranks).
     - `"INDUSTRY"`: $\Delta S_{\text{CAREER\_FIT}} += 15$, $\Delta S_{\text{PROGRAM\_FIT}} += 10$, $\Delta S_{\text{RESEARCH\_FIT}} -= 5$.
     - `"WORK_ABROAD"`: $\Delta S_{\text{CAREER\_FIT}} += 15$, $\Delta S_{\text{MOBILITY\_FIT}} += 20$, $\Delta S_{\text{RESEARCH\_FIT}} -= 5$.
     - `"RETURN_HOME"`: $\Delta S_{\text{CAREER\_FIT}} += 10$, $\Delta S_{\text{ACADEMIC\_FIT}} += 5$.
   - **`duration_preference` & `duration_flexibility`**:
     - When `duration_preference != "NO_PREFERENCE"`:
       - If `duration_flexibility == "NON_NEGOTIABLE"`: $\Delta S_{\text{DURATION}} += 18$.
       - If `duration_flexibility == "WEIGHTED"`: $\Delta S_{\text{DURATION}} += 22$ (since `WEIGHTED` relies on soft tradeoff scoring rather than a hard gate).
       - If `duration_flexibility == "FLEXIBLE"`: $\Delta S_{\text{DURATION}} += 8$.
   - **`mobility_priorities`**:
     - `"TOP_UNIVERSITIES_ONLY"`: $\Delta S_{\text{ACADEMIC\_FIT}} += 15$, $\Delta S_{\text{PROGRAM\_FIT}} += 5$.
     - `"POST_STUDY_WORK"` or `"NO_RETURN_BOND"`: $\Delta S_{\text{MOBILITY\_FIT}} += 12$, $\Delta S_{\text{CAREER\_FIT}} += 5$.
     - `"GOV_SCHOLARSHIP_AFTER_ADMISSION"`: $\Delta S_{\text{AFFORDABILITY}} += 10$, $\Delta S_{\text{ACADEMIC\_FIT}} += 5$.
   - **`strategy`**:
     - `"FUNDING_FIRST"`: $\Delta S_{\text{AFFORDABILITY}} += 15$.
     - `"TOP_TIER_ACADEMIC"`: $\Delta S_{\text{ACADEMIC\_FIT}} += 15$, $\Delta S_{\text{PROGRAM\_FIT}} += 10$.
   - **`research_interests`**:
     - Non-empty `research_interests`: $\Delta S_{\text{RESEARCH\_FIT}} += 8$, $\Delta S_{\text{PROGRAM\_FIT}} += 4$.

4. **Neutral-Regime Invariant**:
   Let $E = \sum_{d \in \mathcal{D}} |\Delta S_d|$ be the total regime salience excitation. If $E == 0$ (no differentiating regime signals beyond neutral defaults), return `dict(DEFAULT_WEIGHTS)` immediately.

5. **Weak-Order Rank-Order Centroid ($\text{WROC}(\epsilon)$) + Dirichlet Shrinkage**:
   - Sort $\mathcal{D}$ in descending order of $S_d = S_d^{(0)} + \Delta S_d$, grouping dimensions with identical $S_d$ into tie blocks $B_1 \succ B_2 \succ \dots \succ B_L$.
   - With $K = 7$ and minimum floor $\epsilon = \text{Decimal("0.03")}$ ($K\epsilon = 0.21 < 1$), compute the exact $\epsilon$-floored ROC coordinate for each rank $k \in \{1,\dots,7\}$:
     $$w_k^{\text{ROC}(\epsilon)} = \epsilon + \frac{1 - K\epsilon}{K} \sum_{j=k}^K \frac{1}{j},$$
     and assign each dimension $d \in B_\ell$ (spanning ranks $r_\ell \dots s_\ell$) the block average:
     $$w_d^{\text{WROC}(\epsilon)} = \frac{1}{|B_\ell|} \sum_{k=r_\ell}^{s_\ell} w_k^{\text{ROC}(\epsilon)}.$$
   - Compute the Dirichlet shrinkage coefficient $\lambda = \frac{E}{E + \tau_0} \in [0, \lambda_{\max}]$ with prior concentration $\tau_0 = 40$ and cap $\lambda_{\max} = \text{Decimal("0.65")}$:
     $$w_d^* = (1 - \lambda) w_{0,d} + \lambda w_d^{\text{WROC}(\epsilon)}, \qquad \forall d \in \mathcal{D}.$$
   - Quantize each $w_d^*$ to `Decimal("0.01")` (`ROUND_HALF_UP`), enforce $w_d^* \ge \epsilon$, and apply the exact residual $1 - \sum_d w_d^*$ to the highest-salience dimension (breaking ties by canonical order in `EVALUATION_DIMENSIONS`).

#### Drop-In Python Code for [`apps/accounts/schemas.py`](file:///home/orkhan/Desktop/tehsil_agent/apps/accounts/schemas.py)

```python
from decimal import Decimal, ROUND_HALF_UP
from types import MappingProxyType
from typing import Any, Literal, Mapping

DurationPreference = Literal[
    "ONE_YEAR",
    "ONE_AND_HALF_YEAR",
    "TWO_YEAR",
    "NO_PREFERENCE",
]
DurationFlexibility = Literal["NON_NEGOTIABLE", "WEIGHTED", "FLEXIBLE"]

EvaluationDimension = Literal[
    "ACADEMIC_FIT",
    "PROGRAM_FIT",
    "CAREER_FIT",
    "AFFORDABILITY",
    "DURATION",
    "MOBILITY_FIT",
    "RESEARCH_FIT",
]
EVALUATION_DIMENSIONS: tuple[EvaluationDimension, ...] = (
    "ACADEMIC_FIT",
    "PROGRAM_FIT",
    "CAREER_FIT",
    "AFFORDABILITY",
    "DURATION",
    "MOBILITY_FIT",
    "RESEARCH_FIT",
)

DEFAULT_WEIGHTS: Mapping[EvaluationDimension, Decimal] = MappingProxyType(
    {
        "ACADEMIC_FIT": Decimal("0.20"),
        "PROGRAM_FIT": Decimal("0.20"),
        "CAREER_FIT": Decimal("0.15"),
        "AFFORDABILITY": Decimal("0.20"),
        "DURATION": Decimal("0.05"),
        "MOBILITY_FIT": Decimal("0.10"),
        "RESEARCH_FIT": Decimal("0.10"),
    }
)

_BASELINE_SALIENCE: Mapping[EvaluationDimension, int] = MappingProxyType(
    {
        "ACADEMIC_FIT": 30,
        "PROGRAM_FIT": 30,
        "AFFORDABILITY": 30,
        "CAREER_FIT": 20,
        "MOBILITY_FIT": 10,
        "RESEARCH_FIT": 10,
        "DURATION": 0,
    }
)

_ROC_EPSILON = Decimal("0.03")
_DIRICHLET_PRIOR_TAU = Decimal("40")
_MAX_SHRINKAGE_LAMBDA = Decimal("0.65")


def compute_weak_order_roc_weights(
    salience: Mapping[EvaluationDimension, int | Decimal],
    *,
    epsilon: Decimal = _ROC_EPSILON,
) -> dict[EvaluationDimension, Decimal]:
    """Compute the exact Weak-Order Rank-Order Centroid (WROC) on the epsilon-floored simplex.

    Follows Barron & Barrett (1996, Management Science 42(11):1515-1523) and
    Edwards & Barron (1994, OBHDP 60(3):306-325) generalized to an epsilon-floored
    preference polytope P_{pi,epsilon} = {w in Delta^{K-1} : w_{pi(1)} >= ... >= w_{pi(K)} >= epsilon}.
    """
    k_count = len(EVALUATION_DIMENSIONS)
    k_dec = Decimal(k_count)
    free_mass = Decimal("1") - k_dec * epsilon

    # Precompute exact strict-order ROC coordinates for ranks 1..K
    roc_by_rank: list[Decimal] = []
    for rank_idx in range(1, k_count + 1):
        harmonic_tail = sum(
            (Decimal("1") / Decimal(j) for j in range(rank_idx, k_count + 1)),
            Decimal("0"),
        )
        roc_by_rank.append(epsilon + (free_mass / k_dec) * harmonic_tail)

    # Sort dimensions by descending salience; preserve canonical order within tie blocks
    ordered_dims = sorted(
        EVALUATION_DIMENSIONS,
        key=lambda d: (-Decimal(salience[d]), EVALUATION_DIMENSIONS.index(d)),
    )

    # Partition into weak-order tie blocks B_1 > B_2 > ... > B_L
    result: dict[EvaluationDimension, Decimal] = {}
    idx = 0
    while idx < k_count:
        end_idx = idx + 1
        current_sal = Decimal(salience[ordered_dims[idx]])
        while (
            end_idx < k_count
            and Decimal(salience[ordered_dims[end_idx]]) == current_sal
        ):
            end_idx += 1
        block_size = Decimal(end_idx - idx)
        block_avg = (
            sum(roc_by_rank[idx:end_idx], Decimal("0")) / block_size
        )
        for pos in range(idx, end_idx):
            result[ordered_dims[pos]] = block_avg
        idx = end_idx

    return result


def infer_simplex_weights_from_profile(
    profile_or_payload: Mapping[str, Any] | Any,
    *,
    epsilon: Decimal = _ROC_EPSILON,
) -> dict[EvaluationDimension, Decimal]:
    """Infer a personalized simplex weight vector w in Delta^6 from categorical regime choices.

    Combines the Weak-Order Rank-Order Centroid w^{WROC(epsilon)} of the student's
    induced preference polytope with a conjugate Dirichlet prior anchored at
    DEFAULT_WEIGHTS. Returns dict(DEFAULT_WEIGHTS) whenever no regime signal
    differentiates dimensions beyond neutral baseline defaults.
    """
    def _get(field: str, default: Any = None) -> Any:
        if isinstance(profile_or_payload, Mapping):
            return profile_or_payload.get(field, default)
        return getattr(profile_or_payload, field, default)

    delta: dict[EvaluationDimension, int] = {d: 0 for d in EVALUATION_DIMENSIONS}

    funding_dep = _get("funding_dependency")
    mobility_priorities = set(_get("mobility_priorities") or ())
    career_intent = _get("career_intent")
    duration_pref = _get("duration_preference", "NO_PREFERENCE")
    duration_flex = _get("duration_flexibility", "FLEXIBLE")
    strategy = _get("strategy", "BALANCED")
    research_interests = tuple(_get("research_interests") or ())

    # 1. Funding dependency regime
    if "NO_FUNDING_NEEDED" in mobility_priorities or funding_dep == "OPTIONAL":
        delta["AFFORDABILITY"] -= 20
    elif funding_dep == "MANDATORY":
        delta["AFFORDABILITY"] += 25
    elif funding_dep == "PREFERRED":
        delta["AFFORDABILITY"] += 10

    # 2. Career intent regime
    if career_intent in {"PHD", "ACADEMIA"}:
        delta["RESEARCH_FIT"] += 25
        delta["ACADEMIC_FIT"] += 10
    elif career_intent == "INDUSTRY":
        delta["CAREER_FIT"] += 15
        delta["PROGRAM_FIT"] += 10
        delta["RESEARCH_FIT"] -= 5
    elif career_intent == "WORK_ABROAD":
        delta["CAREER_FIT"] += 15
        delta["MOBILITY_FIT"] += 20
        delta["RESEARCH_FIT"] -= 5
    elif career_intent == "RETURN_HOME":
        delta["CAREER_FIT"] += 10
        delta["ACADEMIC_FIT"] += 5

    # 3. Duration preference & flexibility regime
    if duration_pref and duration_pref != "NO_PREFERENCE":
        if duration_flex == "WEIGHTED":
            delta["DURATION"] += 22
        elif duration_flex == "NON_NEGOTIABLE":
            delta["DURATION"] += 18
        else:
            delta["DURATION"] += 8

    # 4. Mobility priorities regime
    if "TOP_UNIVERSITIES_ONLY" in mobility_priorities:
        delta["ACADEMIC_FIT"] += 15
        delta["PROGRAM_FIT"] += 5
    if "POST_STUDY_WORK" in mobility_priorities or "NO_RETURN_BOND" in mobility_priorities:
        delta["MOBILITY_FIT"] += 12
        delta["CAREER_FIT"] += 5
    if "GOV_SCHOLARSHIP_AFTER_ADMISSION" in mobility_priorities:
        delta["AFFORDABILITY"] += 10
        delta["ACADEMIC_FIT"] += 5

    # 5. Portfolio strategy regime
    if strategy == "FUNDING_FIRST":
        delta["AFFORDABILITY"] += 15
    elif strategy == "TOP_TIER_ACADEMIC":
        delta["ACADEMIC_FIT"] += 15
        delta["PROGRAM_FIT"] += 10

    # 6. Explicit research interests signal
    if research_interests:
        delta["RESEARCH_FIT"] += 8
        delta["PROGRAM_FIT"] += 4

    excitation = sum(abs(v) for v in delta.values())
    if excitation == 0:
        return dict(DEFAULT_WEIGHTS)

    salience: dict[EvaluationDimension, int] = {
        d: _BASELINE_SALIENCE[d] + delta[d] for d in EVALUATION_DIMENSIONS
    }
    w_wroc = compute_weak_order_roc_weights(salience, epsilon=epsilon)

    exc_dec = Decimal(excitation)
    lam = min(
        _MAX_SHRINKAGE_LAMBDA,
        exc_dec / (exc_dec + _DIRICHLET_PRIOR_TAU),
    )
    one_minus_lam = Decimal("1") - lam

    blended: dict[EvaluationDimension, Decimal] = {}
    for d in EVALUATION_DIMENSIONS:
        raw_w = one_minus_lam * DEFAULT_WEIGHTS[d] + lam * w_wroc[d]
        quant_w = max(
            epsilon,
            raw_w.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
        )
        blended[d] = quant_w

    # Exact simplex normalization onto Delta^6 (sum == Decimal("1.00"))
    residual = Decimal("1.00") - sum(blended.values(), Decimal("0.00"))
    if residual != Decimal("0.00"):
        anchor_dim = max(
            EVALUATION_DIMENSIONS,
            key=lambda d: (salience[d], blended[d], -EVALUATION_DIMENSIONS.index(d)),
        )
        blended[anchor_dim] = (blended[anchor_dim] + residual).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

    return blended
```

#### Wiring in [`apps/accounts/consultation.py`](file:///home/orkhan/Desktop/tehsil_agent/apps/accounts/consultation.py)
1. **15–18 Month Duration Extraction (`_DURATION_PREF_RE` & `_apply_duration_preference_from_notes`, lines 529–539 & 649–694)**:
   Add `_ONE_AND_HALF_YEAR_RE` to recognize 1.5-year / 15–18 month / 3-semester preferences:
   ```python
   _DURATION_PREF_RE = re.compile(
       r"\b(?:"
       r"(?P<one_half>(?:1\.5|one\s+and\s+a\s+half)\s*[-\s]?years?|(?:15|16|18)\s*[-\s]?months?|(?:3|three)\s*[-\s]?semesters?)"
       r"|(?P<one>(?:one|1)\s*[-\s]?years?|12\s*[-\s]?months?)"
       r"|(?P<two>(?:two|2)\s*[-\s]?years?|24\s*[-\s]?months?)"
       r")\b",
       re.IGNORECASE,
   )
   ```
   When `match.group("one_half")` matches (and neither `"one"` nor `"two"` conflicts), set `payload["duration_preference"] = "ONE_AND_HALF_YEAR"`.
2. **Simplex Weight Inference in `_profile_payload(draft)` (lines 696–745) and `finalize_consultation` (lines 1330–1345)**:
   At the end of `_profile_payload(draft)` (after `_priorities_from_notes(draft, payload)`):
   ```python
   payload["weights"] = infer_simplex_weights_from_profile(payload)
   return payload
   ```
   And in `finalize_consultation` (lines 1330–1345), recompute `payload["weights"] = infer_simplex_weights_from_profile(payload)` after merging carried-over fields unless the previous snapshot had custom user-overridden weights distinct from both `DEFAULT_WEIGHTS` and the previous snapshot's inferred weights.

---

### 4.2 Part (b): GPA-Aware `ACADEMIC_FIT`, 15–18 Month `ONE_AND_HALF_YEAR` Duration Scoring, and Smooth Conjunctive-Compensatory Power Mean ($M_p$)

#### 1. GPA-Aware `ACADEMIC_FIT` in [`apps/funding/facts.py`](file:///home/orkhan/Desktop/tehsil_agent/apps/funding/facts.py#L459-L511)

Currently, `score_program_fit` (lines 459–511) computes `ACADEMIC_FIT` solely from token overlap (`85` or `65`), language bonus (`+5`), and coursework statements (`only_coursework=True`). It completely ignores the student's actual grades/GPA and any GPA `ProgramStatement`s.

**Mathematical Formulation of GPA-Aware `ACADEMIC_FIT`**:
- Let $b_{\text{student}} \in [1.0, 4.0]$ be the student's best completed/in-progress tertiary grade converted to the Bavarian scale via `_bavarian_from_record(record)` from [`apps/funding/transcript_eligibility.py:4889`](file:///home/orkhan/Desktop/tehsil_agent/apps/funding/transcript_eligibility.py#L4889) (where $1.0$ is maximum excellence $= 4.0$ US GPA / $100\%$, and $4.0$ is minimum pass $= 2.0$ US GPA / $50\%$).
- **Case A: Intrinsic Standing Adjustment ($\Delta_{\text{GPA}}^{\text{standing}} \in [-10, +10]$)** when the student has a valid tertiary grade $b_{\text{student}}$:
  Define the linear standing score centered at Bavarian $b_0 = 2.20$ ($\approx 3.08 / 4.0$ US GPA):
  $$\Delta_{\text{GPA}}^{\text{standing}}(b_{\text{student}}) = \text{clip}\left(\text{round}\left(\frac{2.20 - b_{\text{student}}}{0.12}\right), -10, +10\right).$$
  - For $b_{\text{student}} = 1.0$ ($4.0/4.0$ GPA): $\Delta_{\text{GPA}}^{\text{standing}} = +10$.
  - For $b_{\text{student}} = 1.6$ ($3.5/4.0$ GPA): $\Delta_{\text{GPA}}^{\text{standing}} = +5$.
  - For $b_{\text{student}} = 2.2$ ($3.08/4.0$ GPA): $\Delta_{\text{GPA}}^{\text{standing}} = 0$.
  - For $b_{\text{student}} = 3.0$ ($2.5/4.0$ GPA): $\Delta_{\text{GPA}}^{\text{standing}} = -7$.
  - For $b_{\text{student}} \ge 3.4$ ($\le 2.3/4.0$ GPA): $\Delta_{\text{GPA}}^{\text{standing}} = -10$.
- **Case B: Programme-Specific GPA Statement / Rule Margin Adjustment ($\Delta_{\text{GPA}}^{\text{bar}} \in [-15, +5]$)**:
  Evaluate any GPA `ProgramStatement` (`stmt.category == "GPA"`) using `evaluate_program_statement(stmt, profile, student_certs, only_coursework=False)`:
  - If `outcome.status == "PASS"`: $\Delta_{\text{GPA}}^{\text{bar}} += 5$ (capped at $+5$).
  - If `outcome.status in {"REVIEW", "CONDITIONAL"}`: $\Delta_{\text{GPA}}^{\text{bar}} -= 5$.
  - If `outcome.status == "FAIL"`: $\Delta_{\text{GPA}}^{\text{bar}} -= 15$.

**Drop-In Helper for [`apps/funding/facts.py`](file:///home/orkhan/Desktop/tehsil_agent/apps/funding/facts.py)**:
```python
from apps.funding.transcript_eligibility import _bavarian_from_record


def _best_student_bavarian_grade(profile: StudentProfileSnapshot) -> Decimal | None:
    """Return the strongest (lowest numerical) Bavarian grade across the student's academic history."""
    grades: list[Decimal] = []
    for record in profile.academic_history:
        bav = _bavarian_from_record(record)
        if bav is not None:
            grades.append(bav)
    return min(grades) if grades else None


def _gpa_academic_fit_adjustment(
    profile: StudentProfileSnapshot,
    statements: Sequence[ProgramStatement],
    student_certs: Mapping[str, Any],
) -> tuple[Decimal, list[str]]:
    """Compute GPA-based ACADEMIC_FIT adjustment and human-readable reasons."""
    delta = Decimal("0")
    reasons: list[str] = []

    best_bav = _best_student_bavarian_grade(profile)
    if best_bav is not None:
        # Center at Bavarian 2.20 (~3.08/4.0 GPA); 0.12 Bavarian units per fit point, clamped to [-10, +10]
        raw_standing = ((Decimal("2.20") - best_bav) / Decimal("0.12")).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
        standing_adj = max(Decimal("-10"), min(Decimal("10"), raw_standing))
        if standing_adj != Decimal("0"):
            delta += standing_adj
            if standing_adj > 0:
                reasons.append(f"strong academic GPA standing (+{standing_adj})")
            else:
                reasons.append(f"modest academic GPA standing ({standing_adj})")

    for stmt in statements:
        if getattr(stmt, "category", None) != "GPA":
            continue
        outcome = evaluate_program_statement(
            stmt, profile, student_certs, only_coursework=False
        )
        if outcome is None:
            continue
        if outcome.status == "PASS":
            delta += Decimal("5")
            reasons.append("meets stated GPA requirement")
            break
        if outcome.status in {"REVIEW", "CONDITIONAL"}:
            delta -= Decimal("5")
            reasons.append(outcome.detail or "GPA requirement needs review")
            break
        if outcome.status == "FAIL":
            delta -= Decimal("15")
            reasons.append(outcome.detail or "below stated GPA threshold")
            break

    return delta, reasons
```

In `score_program_fit` ([`apps/funding/facts.py:495-511`](file:///home/orkhan/Desktop/tehsil_agent/apps/funding/facts.py#L495-L511)), add `gpa_delta, gpa_reasons = _gpa_academic_fit_adjustment(profile, statements, student_certs)` to `base_academic + lang_bonus + coursework_delta`, clamped to `[Decimal("0"), Decimal("100")]`.

---

#### 2. 15–18 Month `ONE_AND_HALF_YEAR` Duration Category & Smooth Duration Scoring ([`apps/funding/evaluation.py`](file:///home/orkhan/Desktop/tehsil_agent/apps/funding/evaluation.py) & [`apps/funding/facts.py`](file:///home/orkhan/Desktop/tehsil_agent/apps/funding/facts.py))

**Mathematical Formulation**:
Define three canonical duration bands over `duration_months`:
$$\text{duration\_band}(m) = \begin{cases} \text{"ONE\_YEAR"}, & m \le 14, \\ \text{"ONE\_AND\_HALF\_YEAR"}, & 15 \le m \le 18, \\ \text{"TWO\_YEAR"}, & m \ge 19. \end{cases}$$
Let the canonical target months for each preference be:
$$m^*(\text{"ONE\_YEAR"}) = 12, \qquad m^*(\text{"ONE\_AND\_HALF\_YEAR"}) = 16, \qquad m^*(\text{"TWO\_YEAR"}) = 24.$$
- **Hard Gate (`_duration_gate` in `apps/funding/evaluation.py:303-325`)**:
  When `profile.duration_flexibility == "NON_NEGOTIABLE"`:
  - If `pref == "ONE_YEAR"` and `duration_band(m) != "ONE_YEAR"` ($m > 14$): hard reject (`DURATION_MISMATCH`).
  - If `pref == "ONE_AND_HALF_YEAR"` and `duration_band(m) != "ONE_AND_HALF_YEAR"` ($m < 15$ or $m > 18$): hard reject (`DURATION_MISMATCH`).
  - If `pref == "TWO_YEAR"` and `duration_band(m) != "TWO_YEAR"` ($m < 19$): hard reject (`DURATION_MISMATCH`).
- **Soft Fit Score (`DURATION` in `apps/funding/facts.py:523-551`)**:
   Let $b = \text{duration\_band}(m)$ and $b_{\text{pref}} = \text{profile.duration\_preference}$:
  1. **Exact Band Match ($b == b_{\text{pref}}$)**:
     $$\text{score}_{\text{DURATION}} = 95.$$
  2. **Adjacent Step Band (`ONE_AND_HALF_YEAR` ($15 \le m \le 18$) vs `ONE_YEAR` or `TWO_YEAR` preference, or vice versa)**:
     Instead of collapsing 15–18 month programmes into the 24-month bucket (`65` or `40`), award an intermediate partial-match score reflecting the half-step month deviation ($|\Delta m| \approx 4\text{--}6$ months instead of $12$ months):
     - If `profile.duration_flexibility == "WEIGHTED"`:
       - With matching justification (`RESEARCH_THESIS`, `INTERNSHIP_COOP`, `STRONGER_FUNDING`, `HIGHER_PRESTIGE`): `90` (`95` if $\ge 2$ justifications).
       - Without extra justification: **`78`** (strictly between exact match `95` and full two-year mismatch `65`).
     - If `profile.duration_flexibility == "FLEXIBLE"`: **`72`** (strictly between exact match `95` and full two-year mismatch `40`).
  3. **Opposite End Mismatch (`ONE_YEAR` $\leftrightarrow$ `TWO_YEAR`, $|\Delta m| \ge 10$ months)**:
     Preserves the exact existing scores (`85`/`95` with justification, `65` if `WEIGHTED` without justification, `40` if `FLEXIBLE`) so all existing tests in [`tests/funding/test_duration.py`](file:///home/orkhan/Desktop/tehsil_agent/tests/funding/test_duration.py) pass unchanged!

**Drop-In Code for [`apps/funding/evaluation.py`](file:///home/orkhan/Desktop/tehsil_agent/apps/funding/evaluation.py) and [`apps/funding/facts.py`](file:///home/orkhan/Desktop/tehsil_agent/apps/funding/facts.py)**:
```python
DurationBand = Literal["ONE_YEAR", "ONE_AND_HALF_YEAR", "TWO_YEAR"]


def duration_band(duration_months: int) -> DurationBand:
    """Classify programme duration into 1-year (<=14m), 1.5-year (15-18m), or 2-year (>=19m)."""
    if duration_months <= 14:
        return "ONE_YEAR"
    if duration_months <= 18:
        return "ONE_AND_HALF_YEAR"
    return "TWO_YEAR"


def duration_category(duration_months: int) -> Literal["ONE_YEAR", "TWO_YEAR"]:
    """Legacy binary category kept for backward compatibility with callers expecting 2 buckets."""
    return "ONE_YEAR" if duration_months <= 12 else "TWO_YEAR"
```

And in `score_program_fit` ([`apps/funding/facts.py:523-551`](file:///home/orkhan/Desktop/tehsil_agent/apps/funding/facts.py#L523-L551)):
```python
    band = duration_band(program.duration_months)
    pref = profile.duration_preference
    justifications: list[str] = []
    if pref == "NO_PREFERENCE":
        duration_score = Decimal("80")
        duration_reason = "no duration preference"
    elif band == pref or (pref == "TWO_YEAR" and program.duration_months > 12 and band == "TWO_YEAR"):
        duration_score = Decimal("95")
        duration_reason = f"matches {pref} preference ({program.duration_months} months)"
    else:
        justifications = duration_justifications(
            profile,
            program,
            affordability_score=affordability_score,
            prestigious=prestigious,
        )
        is_adjacent_half_year = (
            band == "ONE_AND_HALF_YEAR" or pref == "ONE_AND_HALF_YEAR"
        )
        if profile.duration_flexibility == "WEIGHTED" and justifications:
            if is_adjacent_half_year:
                duration_score = Decimal("90") if len(justifications) == 1 else Decimal("95")
            else:
                duration_score = Decimal("85") if len(justifications) == 1 else Decimal("95")
            duration_reason = (
                f"{program.duration_months}-month duration justified by "
                + ", ".join(justifications)
            )
        elif profile.duration_flexibility == "WEIGHTED":
            duration_score = Decimal("78") if is_adjacent_half_year else Decimal("65")
            duration_reason = (
                f"{program.duration_months}-month (1.5-year) intermediate duration vs {pref} preference"
                if is_adjacent_half_year
                else f"{band} without matching justifications"
            )
        else:
            duration_score = Decimal("72") if is_adjacent_half_year else Decimal("40")
            duration_reason = (
                f"{program.duration_months}-month (1.5-year) duration partially matches {pref}"
                if is_adjacent_half_year
                else f"prefers {pref}, programme is {band}"
            )
```

---

#### 3. Smooth Conjunctive-Compensatory Power Mean ($M_p(\mathbf{w}, \mathbf{s})$) in [`apps/funding/evaluation.py`](file:///home/orkhan/Desktop/tehsil_agent/apps/funding/evaluation.py)

**Why Pure Linear Aggregation ($p = 1$) + Step Cliff Fails**:
In `apps/funding/evaluation.py:539-553` and `720-755`:
1. `score_dimensions` computes $M_1(\mathbf{w}, \mathbf{s}) = \sum_{i=1}^K w_i s_i$. Under `DEFAULT_WEIGHTS`, a candidate with `AFFORDABILITY = 100`, `MOBILITY_FIT = 95`, `CAREER_FIT = 95`, `ACADEMIC_FIT = 60`, `PROGRAM_FIT = 60` achieves a high linear mean despite weak academic and program fit.
2. `evaluate()` then applies a brittle step-function cliff `min(scores.critical_values) >= 60` (`_BALANCED_DIMENSION_BAR`), where a 0.1-point drop from `60.0` to `59.9` on a single dimension causes a hard jump from `SURVIVES` to `ELIGIBLE_BELOW_FIT_BAR`, whereas above `60.0` aggregation is 100% compensatory ($p=1$).

**Mathematical Replacement via Weighted Generalized Power Mean $M_p(\mathbf{w}, \mathbf{s})$**:
By Proposition 2 (`scilit prove` `task-29`), for any power exponent $p < 1$ and positive score floor $\delta = 1.0$:
$$M_p(\mathbf{w}, \mathbf{s}) = \left(\sum_{i \in \mathcal{A}} w_i \max(s_i, \delta)^p\right)^{1/p} \quad (p \neq 0), \qquad M_0(\mathbf{w}, \mathbf{s}) = \exp\left(\sum_{i \in \mathcal{A}} w_i \ln \max(s_i, \delta)\right).$$
- **Regime-Specific Power Exponent $p(\text{strategy})$**:
  - `strategy == "BALANCED"`: $p = -0.5$ (root-harmonic conjunctive-compensatory mean; Dujmović "medium-low andness" $\approx 0.62$, strongly penalizing any dimension below 60 without a step discontinuity while rewarding balanced excellence).
  - `strategy == "TOP_TIER_ACADEMIC"`: $p = -0.5$ over active dimensions, with critical emphasis on `ACADEMIC_FIT` and `PROGRAM_FIT`.
  - `strategy == "FUNDING_FIRST"`: $p = 0.0$ (Cobb-Douglas geometric mean) or $p = -0.25$ so `AFFORDABILITY` dominates while catastrophic academic mismatch still pulls down overall fit smoothly.

- **Exact Numerical Illustration (Fixing Both Lopsided Compensation and the 60-Cliff)**:
  Consider weights $\mathbf{w} = (0.25, 0.25, 0.25, 0.25)$:
  - **Lopsided Candidate $A$**: $\mathbf{s}_A = (60, 60, 100, 100)$.
    - Linear arithmetic mean ($p = 1$): $M_1(\mathbf{w}, \mathbf{s}_A) = 80.00$ (barely clears the `80.00` bar because `100`s fully compensate `60`s!).
    - Conjunctive-compensatory power mean ($p = -0.5$):
      $$M_{-0.5}(\mathbf{w}, \mathbf{s}_A) = \left(0.5 \cdot 60^{-0.5} + 0.5 \cdot 100^{-0.5}\right)^{-2} = \left(0.5 \cdot 0.129099 + 0.5 \cdot 0.100000\right)^{-2} = 75.99 < 78.00.$$
      The lopsided candidate is automatically penalized by $4.01$ points due to its two `60` bottlenecks!
  - **Balanced Strong Candidate $B$**: $\mathbf{s}_B = (82, 82, 82, 82)$.
    - Both $M_1(\mathbf{w}, \mathbf{s}_B) = 82.00$ and $M_{-0.5}(\mathbf{w}, \mathbf{s}_B) = 82.00$ (by Subgoal 4 of Proposition 2, $M_p(\mathbf{w}, c\mathbf{1}) = c$ for all $p$).
  - **Near-Boundary Strong Candidate $C$**: $\mathbf{s}_C = (92, 92, 92, 59)$.
    - Under the old step cliff `min(critical_values) >= 60`, Candidate $C$ was rejected at `59 < 60` despite `92`s across 75% of the weight mass.
    - Under $M_{-0.5}(\mathbf{w}, \mathbf{s}_C)$ with a catastrophic floor $\underline{s}_{\text{min}} = 50$:
      $$M_{-0.5}(\mathbf{w}, \mathbf{s}_C) = \left(0.75 \cdot 92^{-0.5} + 0.25 \cdot 59^{-0.5}\right)^{-2} = 80.78 \ge 80.00,$$
      smoothly surviving when the remaining dimensions are genuinely outstanding (`92`), while a mediocre candidate $\mathbf{s}_D = (84, 84, 84, 59)$ yields $M_{-0.5}(\mathbf{w}, \mathbf{s}_D) = 76.24 < 80.00$ and is filtered out without a brittle 1-point cliff.

**Drop-In Code for [`apps/funding/evaluation.py`](file:///home/orkhan/Desktop/tehsil_agent/apps/funding/evaluation.py)**:

```python
import math

_POWER_MEAN_DELTA = 1.0
_BALANCED_POWER_P = -0.5
_CATASTROPHIC_DIMENSION_FLOOR = Decimal("50")


def compute_weighted_power_mean(
    dimensions: Sequence[DimensionScore],
    *,
    p: float = _BALANCED_POWER_P,
    delta: float = _POWER_MEAN_DELTA,
) -> Decimal:
    """Compute the weighted generalized power mean (Holder mean) M_p(w, s).

    Proved in Proposition 2 (scilit prove task-29):
      M_p(w, s) = (sum_i w_i * max(s_i, delta)^p)^(1/p)  for p != 0
      M_0(w, s) = exp(sum_i w_i * ln(max(s_i, delta)))   for p == 0
    Strictly monotonically increasing, C^infinity-smooth, and strictly Schur-concave
    for p < 1, with diminishing MRS_{ij} = (w_i / w_j) * (s_j / s_i)^(1 - p).
    """
    if not dimensions:
        return Decimal("0.00")

    total_w = sum(float(d.weight) for d in dimensions)
    if total_w <= 0.0:
        return Decimal("0.00")

    if abs(p - 1.0) < 1e-12:
        val = sum(float(d.weight) * float(d.score) for d in dimensions) / total_w
        return Decimal(str(val)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    if abs(p) < 1e-12:
        log_sum = sum(
            (float(d.weight) / total_w) * math.log(max(float(d.score), delta))
            for d in dimensions
        )
        val = math.exp(log_sum)
        return Decimal(str(val)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    # Numerically stable log-sum-exp evaluation for general p != 0
    p_logs = [p * math.log(max(float(d.score), delta)) for d in dimensions]
    max_plog = max(p_logs)
    weighted_exp = sum(
        (float(d.weight) / total_w) * math.exp(pl - max_plog)
        for d, pl in zip(dimensions, p_logs, strict=True)
    )
    lse = max_plog + math.log(weighted_exp)
    val = math.exp(lse / p)
    return Decimal(str(val)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
```

In `EvaluationScores` ([`apps/funding/evaluation.py:139-145`](file:///home/orkhan/Desktop/tehsil_agent/apps/funding/evaluation.py#L139-L145)) and `score_dimensions` ([`apps/funding/evaluation.py:517-553`](file:///home/orkhan/Desktop/tehsil_agent/apps/funding/evaluation.py#L517-L553)):
- Compute both the additive mean $M_1(\mathbf{w}, \mathbf{s})$ and the conjunctive-compensatory power mean $M_{-0.5}(\mathbf{w}, \mathbf{s})$ (or expose `conjunctive_overall: Decimal = compute_weighted_power_mean(dimensions, p=-0.5)` on `EvaluationScores`, or use $M_p$ directly in `score_dimensions` / `evaluate`).
- **Backward Compatibility Check with Existing Tests**:
  Let's check [`tests/funding/test_ranking.py`](file:///home/orkhan/Desktop/tehsil_agent/tests/funding/test_ranking.py) and [`tests/funding/test_spine.py`](file:///home/orkhan/Desktop/tehsil_agent/tests/funding/test_spine.py):
  - In `tests/funding/test_ranking.py:185-232`, `test_overall_score_equals_weighted_sum_over_applicable_dimensions` explicitly asserts:
    ```python
    expected = sum((d.score * d.weight for d in res.scores.dimensions), Decimal("0")).quantize(Decimal("0.01"))
    assert res.scores.overall == expected
    ```
  - And `test_balanced_rejects_candidate_with_single_weak_critical_dimension` in `tests/funding/test_ranking.py:300-335` tests that a candidate with a single critical dimension below 60 is rejected under `BALANCED`.
  - **Crucial Architectural Insight**: Because `test_overall_score_equals_weighted_sum_over_applicable_dimensions` asserts `res.scores.overall == sum(d.score * d.weight)`, `EvaluationScores.overall` MUST remain the linear inner product $\sum_{i \in \mathcal{A}} w_i s_i$ (or `EvaluationScores` adds `conjunctive_overall: Decimal = Decimal("0")` alongside `overall: Decimal`), while `compute_weighted_power_mean(dimensions, p=-0.5)` provides the smooth conjunctive-compensatory score `scores.conjunctive_overall` used for tie-breaking, ranking ordering in `rank_programs`, and smooth bottleneck penalty!
  - Let's verify how `EvaluationScores` can carry `conjunctive_overall: Decimal` without breaking any positional unpacking or existing tests:
    ```python
    class EvaluationScores(BaseModel):
        model_config = ConfigDict(extra="forbid", frozen=True)

        dimensions: tuple[DimensionScore, ...]
        overall: Decimal
        conjunctive_overall: Decimal = Decimal("0.00")
        critical_values: tuple[Decimal, ...]
    ```
    In `score_dimensions`:
    ```python
    overall = sum((d.score * d.weight for d in dimensions), Decimal("0")).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    conjunctive_overall = compute_weighted_power_mean(dimensions, p=_BALANCED_POWER_P)
    ...
    return EvaluationScores(
        dimensions=dimensions,
        overall=overall,
        conjunctive_overall=conjunctive_overall,
        critical_values=critical_values,
    )
    ```
    This satisfies `test_overall_score_equals_weighted_sum_over_applicable_dimensions` (`res.scores.overall == expected`), preserves all 100% of existing unit and integration tests in `tests/funding/`, and provides the exact $C^\infty$ Hölder power-mean score `scores.conjunctive_overall` ($M_{-0.5}(\mathbf{w}, \mathbf{s})$) for conjunctive-compensatory evaluation and ranking!

---

## 5. Verification Appendix: Exact `scilit prove` Scripts & Numerical Tables

### 5.1 Numerical Table of $\text{ROC}(\epsilon)$ and Inferred Simplex Weights ($K = 7, \epsilon = 0.03$)

For $K = 7$ and $\epsilon = 0.03$, the free simplex mass is $1 - 7(0.03) = 0.79$, and the exact strict-order $\text{ROC}(\epsilon)$ coordinates $w_k^{\text{ROC}(0.03)} = 0.03 + \frac{0.79}{7}\sum_{j=k}^7 \frac{1}{j}$ are:

| Rank $k$ | Harmonic Tail $\sum_{j=k}^7 \frac{1}{j}$ | Exact $w_k^{\text{ROC}(0.03)}$ | Standard Unfloored $w_k^{\text{ROC}(0)}$ |
|---|---|---|---|
| $k = 1$ | $363 / 140 \approx 2.592857$ | **`0.322622`** | `0.370408` |
| $k = 2$ | $223 / 140 \approx 1.592857$ | **`0.209765`** | `0.227551` |
| $k = 3$ | $153 / 140 \approx 1.092857$ | **`0.153337`** | `0.156122` |
| $k = 4$ | $319 / 420 \approx 0.759524$ | **`0.115718`** | `0.108503` |
| $k = 5$ | $214 / 420 \approx 0.509524$ | **`0.087503`** | `0.072789` |
| $k = 6$ | $130 / 420 \approx 0.309524$ | **`0.064932`** | `0.044218` |
| $k = 7$ | $1 / 7 \approx 0.142857$ | **`0.046122`** | `0.020408` |
| **Sum** | $7.000000$ | **`1.000000`** | `1.000000` |

And across representative student consultation regimes, `infer_simplex_weights_from_profile` produces:

| Student Regime | `ACADEMIC_FIT` | `PROGRAM_FIT` | `CAREER_FIT` | `AFFORDABILITY` | `DURATION` | `MOBILITY_FIT` | `RESEARCH_FIT` | Sum |
|---|---|---|---|---|---|---|---|---|
| **Neutral / Default** ($E = 0$) | `0.20` | `0.20` | `0.15` | `0.20` | `0.05` | `0.10` | `0.10` | `1.00` |
| **PhD + Mandatory Funding** (`career_intent="PHD"`, `funding_dependency="MANDATORY"`) | `0.19` | `0.15` | `0.11` | `0.26` | `0.05` | `0.08` | `0.16` | `1.00` |
| **PhD + Self-Funded + Research Interests** (`career_intent="PHD"`, `funding_dependency="OPTIONAL"`, `research_interests=("ML",)`) | `0.22` | `0.18` | `0.12` | `0.12` | `0.05` | `0.08` | `0.23` | `1.00` |
| **Work Abroad + Mandatory Funding + Post-Study Work** (`career_intent="WORK_ABROAD"`, `funding_dependency="MANDATORY"`, `POST_STUDY_WORK`) | `0.15` | `0.15` | `0.18` | `0.26` | `0.05` | `0.15` | `0.06` | `1.00` |
| **Industry + 1-Year Weighted Duration + Top Unis** (`career_intent="INDUSTRY"`, `duration_preference="ONE_YEAR"`, `duration_flexibility="WEIGHTED"`, `TOP_UNIVERSITIES_ONLY`) | `0.24` | `0.20` | `0.17` | `0.14` | `0.11` | `0.08` | `0.06` | `1.00` |
