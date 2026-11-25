# Mark-Recapture Unseen-Species Stopping & Hazard-Guided Seasonal Renewal Crawler Scheduling

**Repository**: `tehsil_agent` (`/home/orkhan/Desktop/tehsil_agent`)  
**Scope**: `apps/research/{harness,tally,coverage,tap,hybrid_strategy,cycle_verification}.py`, `apps/funding/cycle_schedule.py`, `apps/research/fetch/{monitor,archive}.py`  
**Author**: Scilit Deep Researcher D  
**Date**: 2026-11-03  

---

## 1. Executive Summary & `scilit` Provenance

This specification resolves two coupled algorithmic bottlenecks in `tehsil_agent`'s open-web discovery and funding-cycle verification pipelines:

1. **Scale-Blind Discovery Stopping & Small-Country Impossibility (`harness.py`, `tally.py`, `coverage.py`, `tap.py`, `hybrid_strategy.py`)**:
   - `hybrid_strategy.py` enforces a hardcoded absolute programme floor (`min_programs_per_country = 5`, `deep_saturation_count = 15`, and `min_warm_programs_per_country = 2`) across all destination countries. In small sovereign jurisdictions where the true population of relevant higher-education institutions or degree programmes is $S \in \{1, 2, 3, 4\}$ (e.g., Luxembourg `LU`, Malta `MT`, Iceland `IS`, Cyprus `CY`, Liechtenstein `LI`, Brunei `BN`), $\Pr(S_{\text{obs}} \ge 5) = 0$ identically: the country can **never** reach `TIER_1_DB_COMPLETE` and perpetually re-triggers live web search on every student consultation.
   - `tap.py` (`_Stage1`) shares a **single global sliding window** (`self.window = deque(maxlen=FIRST_SEARCH_PLATEAU_BATCH)`) across all destination countries and query angles in `coverage` and `local` stages. When the first country in `inputs.destinations` plateaus (or is small), `self.plateaued = True` aborts the entire stage and starves all subsequent countries in `inputs.destinations`.
   - `harness.py` records `state.recaptured` ($R$, the number of authoritative `RegisterEntry` domains re-discovered by open-web sweep queries) and `SweepRun.recaptured`, yet never combines $R$ with the known register size $M$ (`RegisterEntry` count) and sweep capture size $C$ to compute **Chapman's bias-corrected mark-recapture population estimator** $\hat{N}_{\text{Chapman}} = \frac{(M+1)(C+1)}{R+1} - 1$. Nor does `harness.py` or `tally.py` use singleton ($f_1, Q_1$) and doubleton ($f_2, Q_2$) incidence frequencies across queries/providers to compute **bias-corrected Chao1/Chao2 unseen-species richness** $\hat{S}_{\text{Chao1}} = S_{\text{obs}} + \frac{f_1(f_1-1)}{2(f_2+1)}$ or **Good-Turing sample coverage** $\hat{C}_{\text{GT}} = 1 - \frac{f_1}{n}$.

2. **Wall-Clock Wayback Probing & Uniform Monthly Monitor Polling (`cycle_verification.py`, `apps/funding/cycle_schedule.py`, `fetch/monitor.py`)**:
   - In `cycle_verification.py`, Step `1b` (`_step_wayback`) probes the Wayback Machine CDX API at `at = _years_back(run.today, back)` ($1$ and $2$ years prior to the arbitrary wall-clock date `run.today`). Because `fetch/archive.py:capture_near` rejects any snapshot outside `CYCLE_ARCHIVE_SKEW_DAYS` (`archive_skew:<date>`, which `_step_wayback` treats as a **definite refusal** and permanently caches via `mark_looked`!), running verification during the off-season (e.g., July for a scholarship whose call opens in November) either fetches an off-season "applications closed" page or triggers a permanent `archive_skew` refusal.
   - `apps/funding/cycle_schedule.py:next_check` uses a 3-step piecewise-constant heuristic (`7` days, `14` days, `45` days), while `apps/research/fetch/monitor.py:create_monitor` hardcodes a uniform monthly cron `"0 6 1 * *"` ($12$ checks/year, $\Delta t = 30.4\text{ days}$) regardless of the funding call's seasonal opening hazard $\lambda(t)$. By **Cho & Garcia-Molina (2003)** and **Wolf et al. (2002)**, optimal refresh allocation under a fixed annual credit budget $B$ follows the **square-root seasonal renewal hazard rule** $r^*(t) = B \frac{\sqrt{\lambda(t)}}{\int_0^T \sqrt{\lambda(s)}\,ds}$, strictly reducing expected call-opening detection delay by $35\%\text{--}62\%$ under the exact same annual Firecrawl credit ceiling (`FIRECRAWL_MONTHLY_CREDITS`).

### `scilit` Run Provenance

| Tool / Subcommand | Run / Task ID | Profile | Summary | Artifact Path |
| :--- | :--- | :--- | :--- | :--- |
| `scilit find` | `20261103T141803Z-93e45f77` | `argon` | 169 papers consulted across OpenAlex, Semantic Scholar, Crossref, arXiv, Europe PMC; 60 scored; 27 accepted ($\text{score} \ge 2$). | `/home/orkhan/.scilit/runs/20261103T141803Z-93e45f77/report.md` |
| `scilit prove` (Prop. 1, 3-subgoal fan-out + Lakatosian repair) | `step-33` | `argon` | Proved subgoals 1 (Chao1 + Poisson Lagrange identity, 5,059 fuzz instances + SymPy), 2 (Chapman estimator & exactness at $R=C$, 43,826 fuzz instances + SymPy), and 3 (discovered boundary witness $f_1=n \implies \hat{C}_{\text{GT}}=0$, repaired to $\hat{C}_{\text{GT}} \in [0,1]$ and $>0 \iff f_1 < n$, 1,160 fuzz instances + SymPy). | `/home/orkhan/.gemini/antigravity/brain/a87a58f1-20d8-42c3-abe7-5926117abf20/.system_generated/steps/33/output.txt` |
| `scilit prove` (Prop. 1, single-sentence unified verification) | `step-58` | `argon` | `"proved": true`, `"fuzz_verified": true` (6,096 exhaustive & random instances), `"sympy_verified": true`, Chebyshev utopia distance `0.084`. | `/home/orkhan/.gemini/antigravity/brain/a87a58f1-20d8-42c3-abe7-5926117abf20/.system_generated/steps/58/output.txt` |
| `scilit prove` (Prop. 2, variational square-root hazard allocation) | `step-35` | `argon` | `"proved": true`, `"fuzz_verified": true` (15 randomized von Mises hazard profiles vs. SciPy SLSQP), `"sympy_verified": true` (Euler-Lagrange stationarity, strict convexity $\partial^2 \mathcal{L}/\partial r^2 > 0$, Cauchy-Schwarz / Lagrange sum-of-squares). | `/home/orkhan/.gemini/antigravity/brain/a87a58f1-20d8-42c3-abe7-5926117abf20/.system_generated/steps/35/output.txt` |
| `scilit ask` | `20261103T141944Z-8adb9174` | `argon` | 208 papers consulted, 60 scored, 28 accepted ($\text{score} \ge 2$), 8 full texts read (`10.1145/3813822.3814125`, `10.7717/peerj.14540`, `10.2436/20.8080.02.49`, `10.1155/2014/847328`), MiniCheck claim verification completed. | `/home/orkhan/.scilit/runs/20261103T141944Z-8adb9174/report.md` |

---

## 2. Primary Literature & Mathematical Foundations

### 2.1 Bibliography (Verified via `scilit find` `20261103T141803Z-93e45f77` & Primary Sources)

1. **Chao, A. (1984)**. "Nonparametric estimation of the number of classes in a population." *Scandinavian Journal of Statistics*, 11(4), 265–270. JSTOR: `4615964`.
   - Derives the lower-bound species richness estimator $\hat{S}_{\text{Chao1}} = S_{\text{obs}} + \frac{f_1^2}{2 f_2}$ via the Cauchy-Schwarz inequality on Poisson/multinomial frequency expectations, and introduces the finite-sample bias-corrected form $\hat{S}_{\text{Chao1}} = S_{\text{obs}} + \frac{f_1(f_1 - 1)}{2(f_2 + 1)}$ which remains finite when $f_2 = 0$.
2. **Chao, A. (1987)**. "Estimating the population size for capture-recapture data with unequal catchability." *Biometrics*, 43(4), 783–791. DOI: `10.2307/2531532`.
   - Extends Chao1 to replicated incidence/quadrat data (**Chao2**): across $T$ sampling units (queries or search providers), if $Q_1$ entities are detected in exactly one unit and $Q_2$ in exactly two units, $\hat{S}_{\text{Chao2}} = S_{\text{obs}} + \frac{T-1}{T}\frac{Q_1(Q_1 - 1)}{2(Q_2 + 1)}$, accounting for arbitrary heterogeneous catchability across entities.
3. **Good, I. J. (1953)**. "The population frequencies of species and the estimation of population parameters." *Biometrika*, 40(3–4), 237–264. DOI: `10.1093/biomet/40.3-4.237`.
   - Formalizes Alan Turing's **sample coverage** estimator $\hat{C}_{\text{GT}} = 1 - \frac{f_1}{n}$ (with second-order smoothing $\hat{C}_{\text{GT}}^{(2)} = 1 - \frac{f_1}{n} + \frac{2 f_2}{n(n-1)}$ when $f_1 > 0$), where $1 - \hat{C}_{\text{GT}} = \frac{f_1}{n}$ estimates the **missing probability mass**—the probability that the next sampled observation belongs to a previously unseen species (institution/programme).
4. **Chapman, D. G. (1951)**. "Some properties of the hypergeometric distribution with applications to zoological sample censuses." *University of California Publications in Statistics*, 1, 131–160.
   - Proves that the naive Lincoln-Petersen estimator $\hat{N}_{\text{LP}} = \frac{M C}{R}$ has infinite expectation because $\Pr(R = 0) > 0$, whereas $\hat{N}_{\text{Chapman}} = \frac{(M+1)(C+1)}{R+1} - 1$ is strictly finite for all $0 \le R \le \min(M, C)$, exact when $R = C$, and admits the nearly unbiased variance estimator $\widehat{\text{Var}}(\hat{N}_{\text{Chapman}}) = \frac{(M+1)(C+1)(M-R)(C-R)}{(R+1)^2(R+2)}$.
5. **Chao, A., & Colwell, R. K. (2017)**. "Thirty years of progeny from Chao's inequality: Estimating and comparing richness with incidence data and incomplete sampling." *SORT (Statistics and Operations Research Transactions)*, 41(1), 3–54. DOI: `10.2436/20.8080.02.49`.
   - Unifies Chao1, Chao2, and Good-Turing coverage-based stopping rules; demonstrates that standardizing samples by **estimated sample coverage** $\hat{C} \in (0, 1]$ rather than raw sample size or raw species count eliminates small-population bias.
6. **Chao, A., Colwell, R. K., Chiu, C.-H., & Townsend, D. (2017)**. "Seen once or more than once: applying Good–Turing theory to estimate species richness using only unique observations and a species list." *Methods in Ecology and Evolution*, 8(10), 1221–1232. DOI: `10.1111/2041-210x.12768`.
7. **Karsdorp, F. (2022)**. "Demystifying Chao1 with Good-Turing." *OSF Preprints*. DOI: `10.31219/osf.io/tb9w2`.
   - Derives Chao1 directly from Good-Turing frequency-of-frequencies smoothing ($r^* = (r+1)\frac{f_{r+1}}{f_r}$).
8. **Qi, Y., Qi, Z., & Wagh, A. (2026)**. "Coverage-Aware Web Crawling for Domain-Specific Supplier Discovery via a Web–Knowledge–Web Pipeline." *ACM*. DOI: `10.1145/3813822.3814125`.
   - Applies ecological species-richness estimation and capture-recapture directly to domain-specific web entity discovery sweeps, replacing ad-hoc zero-yield batch windows with coverage-ratio stopping.
9. **Paris, T., Çelikkanat, A., & Foppiano, L. (2026)**. "Measuring What the Crawler Sees: Discovery Curves, Core Persistence, and Shell Dynamics in Longitudinal Web Crawls." *arXiv:2607.13636*. DOI: `10.48550/arxiv.2607.13636`.
   - Models longitudinal web crawl discovery curves via Petersen-Lincoln-Chapman mark-recapture and Chao1/Chao2 incidence estimators across crawl waves.
10. **Hajič, J., & Moss, F. C. (2025)**. "Knowing when to stop: insights from ecology for building catalogues, collections, and corpora." *ACM*. DOI: `10.1145/3748336.3748347`.
    - Establishes completeness estimation $\hat{\text{Cov}}_{\text{Chao1}} = \frac{S_{\text{obs}}}{\hat{S}_{\text{Chao1}}}$ as the scale-invariant stopping criterion for heterogeneous catalogue construction across jurisdictions of vastly different sizes.
11. **Pal, S., Bhattacharya, I., & Singh, A. (2026)**. "Blind-Spot Mass: A Good-Turing Framework for Quantifying Deployment Coverage Risk in Machine Learning Systems." *arXiv:2604.05057*. DOI: `10.48550/arxiv.2604.05057`.
12. **Lü, J., & Li, D. (2009)**. "Estimating deep web data source size by capture–recapture method." *Information Retrieval*, 13(1), 70–95. DOI: `10.1007/s10791-009-9107-y`.
13. **Cho, J., & Garcia-Molina, H. (2003)**. "Effective page refresh policies for Web crawlers." *ACM Transactions on Database Systems (TODS)*, 28(4), 390–426. DOI: `10.1145/958942.958945`.
    - Formulates web page modification as a Poisson / renewal process and solves the constrained Lagrange multiplier problem for optimal crawler refresh rates under a bounded fetch budget.
14. **Wolf, J. L., Squillante, M. S., Yu, P. S., Sethuraman, J., & Ozsen, L. (2002)**. "Optimal crawling strategies for web search engines." *Proceedings of the 11th International Conference on World Wide Web (WWW '02)*, 136–147. DOI: `10.1145/511446.511465`.
    - Proves that when staleness cost is proportional to detection delay (time between page update and next crawler check), the optimal polling rate $r^*(t)$ under a resource constraint $\int r(t)\,dt \le B$ is proportional to the **square root of the event intensity** $\sqrt{\lambda(t)}$.
15. **Avrachenkov, K., Patil, K., & Thoppe, G. (2021)**. "Online algorithms for estimating change rates of web pages." *Performance Evaluation*, 145, 102261. DOI: `10.1016/j.peva.2021.102261`.
16. **Zimmert, J., et al. (2025)**. "A Scalable Crawling Algorithm Utilizing Noisy Change-Indicating Signals." *Proceedings of the ACM Web Conference (WWW '25)*. DOI: `10.1145/3696410.3714692`.
17. **Cheng, C.-H., et al. (2023)**. "A more reliable species richness estimator based on the Gamma–Poisson model." *PeerJ*, 11, e14540. DOI: `10.7717/peerj.14540` (retrieved & verified in `scilit ask` `20261103T141944Z-8adb9174`).
    - Uses Good-Turing frequency moment identities ($2\mathbb{E}[f_2]^2 = 3\mathbb{E}[f_1]\mathbb{E}[f_3]$ and $\mathbb{E}[f_1]^2 = 2\mathbb{E}[f_0]\mathbb{E}[f_2]$) to correct Chao1's downward richness bias (and upward coverage bias) under severe detection heterogeneity.
18. **Chao, A., Colwell, R. K., Lin, C.-W., & Gotelli, N. J. (2009)**. "Sufficient sampling for asymptotic minimum species richness estimators." *Ecology*, 90(4), 1125–1133 (retrieved in `scilit ask` `20261103T141944Z-8adb9174`).
    - Derives the exact additional sampling effort required to reach a target fraction $g \in (0, 1)$ of asymptotic Chao1/Chao2 richness.
19. **Béguinot, J. (2014)**. "An Algebraic Derivation of Chao's Estimator of the Number of Species in a Community Highlights the Condition Allowing Chao to Deliver Centered Estimates." *ISRN Ecology*, 2014, 847328. DOI: `10.1155/2014/847328` (retrieved in `scilit ask` `20261103T141944Z-8adb9174`).

---

### 2.2 Mapping Ecological & Renewal Quantities to `tehsil_agent`

| Mathematical Symbol | Ecological / Renewal Meaning | Exact `tehsil_agent` Entity / Database Quantity |
| :--- | :--- | :--- |
| $S$ | True species richness in habitat $c$ | True number of accredited higher-education institutions (Rung 4) or eligible degree programmes (Rung 5) in cell $(c, L, F)$ |
| $S_{\text{obs}}$ | Observed species count | Distinct verified domains (`SweepDiscovery.status == VERIFIED`) or active `Program` rows in cell $(c, L, F)$ |
| $n$ | Total individual sightings / captures | Total domain sightings across all executed queries / providers in the sweep or tap stage ($\sum_{i=1}^{S_{\text{obs}}} X_i$) |
| $f_1$ (or $Q_1$) | Singletons (species seen exactly once) | Verified domains (or programmes) returned by **exactly 1** query / search provider (`len(discovery.returned_by) == 1` or seen in 1 query) |
| $f_2$ (or $Q_2$) | Doubletons (species seen exactly twice) | Verified domains (or programmes) returned by **exactly 2** queries / search providers |
| $\hat{S}_{\text{Chao1}}$ | Bias-corrected Chao1 richness lower bound | $S_{\text{obs}} + \frac{f_1(f_1 - 1)}{2(f_2 + 1)}$ |
| $\hat{C}_{\text{Chao1}}$ | Completeness / richness coverage ratio | $\frac{S_{\text{obs}}}{\hat{S}_{\text{Chao1}}} \in (0, 1]$ (equals $1.0$ iff $f_1 \le 1$) |
| $\hat{C}_{\text{GT}}$ | Good-Turing sample coverage | $1 - \frac{f_1}{n} \in [0, 1]$ (missing mass $\hat{M}_0 = \frac{f_1}{n}$) |
| $M$ | Marked individuals in Sample 1 (Register) | Authoritative `RegisterEntry` institutions in country $c$ with bound domain (`vgm.register_coverage(register).bodies_known`) |
| $C$ | Total individuals captured in Sample 2 (Sweep) | Total distinct institution domains captured in the open-web sweep: $C = S_{\text{obs,novel}} + R$ (`run.verified + run.recaptured`) |
| $R$ | Recaptured marked individuals ($M \cap C$) | `SweepRun.recaptured` (`state.recaptured` in `harness.py`: distinct `RegisterEntry` domains hit by open-web sweep) |
| $\hat{N}_{\text{Chapman}}$ | Bias-corrected Lincoln-Petersen total population | $\frac{(M+1)(C+1)}{R+1} - 1 \ge M + C - R$ |
| $\hat{C}_{\text{Chapman}}$ | Dual-frame register + sweep coverage | $\frac{M + C - R}{\hat{N}_{\text{Chapman}}} = \frac{M + S_{\text{obs,novel}}}{\hat{N}_{\text{Chapman}}} \in (0, 1]$ |
| $\lambda(t)$ | Non-homogeneous seasonal renewal hazard | Instantaneous rate of scholarship call opening or deadline updates at day-of-year $t \in [0, 365.25)$ |
| $\mu_{\text{open}}, \mu_{\text{close}}$ | Seasonal peak hazard phases | Expected call opening day-of-year (`cadence.open_month`, `past_calls`, or intake start minus lead) and deadline day-of-year |
| $r^*(t)$ | Optimal crawler polling rate at day $t$ | $B \frac{\sqrt{\lambda(t)}}{\int_0^T \sqrt{\lambda(s)}\,ds}$, yielding inter-check interval $\Delta t^*(t) = \frac{1}{r^*(t)}$ |

---

## 3. Formal Mathematical Propositions & SymPy Proofs (`scilit prove`)

Both propositions were formally verified via `scilit prove` (`--profile argon`) using automated property-based fuzzing, SciPy numerical optimization, and symbolic verification in SymPy.

### 3.1 Proposition 1: Non-Negativity, Cauchy-Schwarz Lower Bound, and Scale-Invariant Coverage Stopping of Bias-Corrected Chao1 and Chapman Mark-Recapture

> **Proposition 1** (*Verified via `scilit prove` in `step-33` and `step-58`, 6,096 + 50,045 fuzz instances, `sympy_verified: true`*):  
> Let $S_{\text{obs}} \ge 1$, $f_1 \ge 0$, $f_2 \ge 0$, and $n \ge 1$ be integers satisfying $f_1 + f_2 \le S_{\text{obs}} \le n$.
> 1. **Bias-Corrected Chao1 Non-Negativity**: The bias-corrected Chao1 richness estimator
>    $$\hat{S}_{\text{Chao1}} = S_{\text{obs}} + \frac{f_1(f_1 - 1)}{2(f_2 + 1)}$$
>    satisfies $\hat{S}_{\text{Chao1}} \ge S_{\text{obs}}$ for all integers $f_1, f_2 \ge 0$, with strict inequality $\hat{S}_{\text{Chao1}} > S_{\text{obs}}$ if and only if $f_1 \ge 2$, and exact equality $\hat{S}_{\text{Chao1}} = S_{\text{obs}}$ when $f_1 \in \{0, 1\}$.
> 2. **Poisson Abundance Cauchy-Schwarz / Lagrange Lower Bound**: Under independent Poisson sighting counts $X_i \sim \text{Poisson}(\lambda_i)$ with rates $\lambda_i > 0$ for $i = 1, \dots, S$, where $\mathbb{E}[f_k] = \sum_{i=1}^S e^{-\lambda_i} \frac{\lambda_i^k}{k!}$, the expected unseen richness $\mathbb{E}[f_0]$ and expected singletons/doubletons satisfy the exact Lagrange identity
>    $$2\,\mathbb{E}[f_0]\,\mathbb{E}[f_2] - (\mathbb{E}[f_1])^2 = \sum_{1 \le i < j \le S} e^{-(\lambda_i + \lambda_j)}(\lambda_i - \lambda_j)^2 \ge 0,$$
>    so $\mathbb{E}[f_0] \ge \frac{(\mathbb{E}[f_1])^2}{2\,\mathbb{E}[f_2]}$ for any heterogeneous catchability profile $(\lambda_1, \dots, \lambda_S)$, with equality if and only if all institutions have homogeneous catchability $\lambda_1 = \dots = \lambda_S$.
> 3. **Chapman Mark-Recapture Finite-Sample Lower Bound & Exactness**: For any register size $M \ge 1$, sweep capture size $C \ge 1$, and recapture overlap $0 \le R \le \min(M, C)$, Chapman's estimator
>    $$\hat{N}_{\text{Chapman}} = \frac{(M+1)(C+1)}{R+1} - 1$$
>    satisfies the exact algebraic decomposition
>    $$\hat{N}_{\text{Chapman}} - (M + C - R) = \frac{(M - R)(C - R)}{R + 1} \ge 0,$$
>    where $M + C - R = |M \cup C| \ge \max(M, C) \ge 1$ is the total number of distinct institutions known across the register and sweep, and $\hat{N}_{\text{Chapman}}(R = C) = M$ (when every swept institution is already in the register, estimated unseen institutions equal $0$).
> 4. **Scale-Invariant Coverage vs. Fixed-Count Impossibility**: The Chao1 completeness ratio
>    $$\hat{C}_{\text{Chao1}} = \frac{S_{\text{obs}}}{\hat{S}_{\text{Chao1}}} = \frac{2\,S_{\text{obs}}(f_2 + 1)}{2\,S_{\text{obs}}(f_2 + 1) + f_1(f_1 - 1)}$$
>    lies strictly in $(0, 1]$ with $\hat{C}_{\text{Chao1}} = 1 \iff f_1 \le 1$, and the Good-Turing sample coverage $\hat{C}_{\text{GT}} = 1 - \frac{f_1}{n}$ lies in $[0, 1]$ (and strictly in $(0, 1]$ iff $f_1 < n$) for any true population size $S \ge 1$. In contrast, any fixed integer threshold $S_{\text{obs}} \ge K$ (such as `min_programs_per_country = 5` in `hybrid_strategy.py:185`) has completion probability $\Pr(S_{\text{obs}} \ge K) = 0$ whenever $1 \le S < K$, whereas $\hat{C}_{\text{Chao1}} = 1 \ge \tau$ is achieved as soon as all $S$ entities are observed at least twice ($f_1 = 0$) or at most one singleton remains ($f_1 = 1$).

#### Lakatosian Boundary Discovery (`scilit prove` `step-33`)
During subgoal 3 verification in `step-33`, `scilit prove`'s counterexample engine discovered the exact boundary witness $(S=1, S_{\text{obs}}=1, f_1=1, f_2=0, n=1)$, where $\hat{C}_{\text{Chao1}} = 1.0 \in (0, 1]$ because $f_1(f_1 - 1) = 0$, whereas unsmoothed Good-Turing coverage evaluates to $\hat{C}_{\text{GT}} = 1 - 1/1 = 0$. This mathematical distinction is critical for small countries (`LU`, `MT`, `IS`):
- When a country has only $S = 1$ university and it has been seen only once ($n = 1, f_1 = 1$), $\hat{C}_{\text{Chao1}} = 1.0$ optimistically, while $\hat{C}_{\text{GT}} = 0.0$ warns that the single observation has never been corroborated by a second query/provider!
- Once a **second** independent query or provider corroborates that institution ($n = 2, S_{\text{obs}} = 1, f_1 = 0, f_2 = 1$), **both** estimators agree: $\hat{C}_{\text{Chao1}} = 1.0$ and $\hat{C}_{\text{GT}} = 1 - 0/2 = 1.0$.
- Therefore, requiring **joint convergence** $\min(\hat{C}_{\text{Chao1}}, \hat{C}_{\text{GT}}) \ge \tau$ (with $n \ge 2$ corroborating sightings) prevents premature stopping on a single uncorroborated hit ($n=1, f_1=1$) while still allowing a country with $S = 1$ institution to reach $100\%$ verified saturation as soon as its sole institution is recaptured ($f_1 = 0, \hat{C}_{\text{GT}} = 1.0, \hat{C}_{\text{Chao1}} = 1.0$).

#### SymPy Verification Script (`step-58`)
```python
import sympy as sp

# Subgoal 1: Bias-corrected Chao1 estimator lower bound
S_obs, f_1, f_2, n = sp.symbols("S_obs f_1 f_2 n", integer=True, nonnegative=True)
S_hat_Chao1 = S_obs + f_1 * (f_1 - 1) / (2 * (f_2 + 1))
diff_chao1 = S_hat_Chao1 - S_obs
assert sp.simplify(diff_chao1 - f_1 * (f_1 - 1) / (2 * (f_2 + 1))) == 0
assert sp.simplify(diff_chao1.subs(f_1, 0)) == 0
assert sp.simplify(diff_chao1.subs(f_1, 1)) == 0
k = sp.Symbol("k", integer=True, nonnegative=True)
diff_chao1_ge2 = diff_chao1.subs(f_1, k + 2)
assert sp.simplify(diff_chao1_ge2 - (k + 1) * (k + 2) / (2 * (f_2 + 1))) == 0

# Subgoal 2: Poisson abundance expectation and Lagrange's identity
for S in range(1, 6):
    lmbda = sp.symbols(f"lmbda_0:{S}", real=True, positive=True)
    Ef0 = sum(sp.exp(-lmbda[i]) for i in range(S))
    Ef1 = sum(lmbda[i] * sp.exp(-lmbda[i]) for i in range(S))
    Ef2 = sum(sp.Rational(1, 2) * (lmbda[i] ** 2) * sp.exp(-lmbda[i]) for i in range(S))
    lhs = 2 * Ef0 * Ef2 - Ef1**2
    rhs = sum(
        sp.exp(-lmbda[i] - lmbda[j]) * (lmbda[i] - lmbda[j]) ** 2
        for i in range(S)
        for j in range(i + 1, S)
    )
    assert sp.expand(lhs - rhs) == 0

# Subgoal 3: Chapman's mark-recapture estimator identity and boundary value
M, C, R = sp.symbols("M C R", real=True)
N_hat_Chapman = ((M + 1) * (C + 1)) / (R + 1) - 1
lhs_chapman = N_hat_Chapman - (M + C - R)
rhs_chapman = (M - R) * (C - R) / (R + 1)
assert sp.simplify(lhs_chapman - rhs_chapman) == 0
assert sp.simplify(N_hat_Chapman.subs(R, C) - M) == 0

# Subgoal 4: Chao1 coverage and Good-Turing coverage bounds
C_hat_Chao1 = S_obs / S_hat_Chao1
assert (
    sp.simplify(
        1 - C_hat_Chao1 - f_1 * (f_1 - 1) / (2 * S_obs * (f_2 + 1) + f_1 * (f_1 - 1))
    )
    == 0
)
assert sp.simplify(C_hat_Chao1.subs(f_1, 0) - 1) == 0
assert sp.simplify(C_hat_Chao1.subs(f_1, 1) - 1) == 0
C_hat_GT = 1 - f_1 / n
assert sp.simplify(C_hat_GT - (n - f_1) / n) == 0
```

---

### 3.2 Proposition 2: Variational Optimality of Square-Root Seasonal Hazard Allocation for Renewal Crawler Scheduling

> **Proposition 2** (*Verified via `scilit prove` in `step-35`, 15 randomized SLSQP profiles, `sympy_verified: true`*):  
> Let a funding page experience state transitions (call opening or deadline publication) over an annual cycle $[0, T]$ with strictly positive seasonal renewal hazard intensity $\lambda(t) > 0$, modeled as a baseline plus von Mises (circular normal) seasonal pulse:
> $$\lambda(t) = \lambda_0 + \sum_{m \in \{\text{open}, \text{close}\}} A_m \exp\!\left(\kappa_m \cos\!\left(\frac{2\pi(t - \mu_m)}{T}\right)\right), \qquad \lambda_0 > 0, \; A_m \ge 0, \; \kappa_m > 0.$$
> Under a crawler polling rate $r(t) > 0$ constrained by total annual check budget $\int_0^T r(t)\,dt \le B$, where the expected detection delay of an event occurring at time $t$ is $\frac{1}{2 r(t)}$, the expected annual detection delay functional
> $$J[r] = \int_0^T \frac{\lambda(t)}{2\,r(t)}\,dt$$
> is strictly convex on $\{r > 0\}$ and is uniquely minimized by the **square-root hazard allocation**:
> $$r^*(t) = B\,\frac{\sqrt{\lambda(t)}}{\int_0^T \sqrt{\lambda(s)}\,ds}, \qquad \Delta t^*(t) = \frac{1}{r^*(t)} = \frac{\int_0^T \sqrt{\lambda(s)}\,ds}{B\,\sqrt{\lambda(t)}}.$$
> The minimum achievable detection delay is
> $$J[r^*] = \frac{1}{2B}\left(\int_0^T \sqrt{\lambda(t)}\,dt\right)^2 \le \frac{T}{2B}\int_0^T \lambda(t)\,dt = J[r_{\text{unif}}],$$
> where $r_{\text{unif}}(t) = B/T$ is the uniform monthly schedule (`MONITOR_CRON = "0 6 1 * *"` in `fetch/monitor.py:28`), with strict inequality $J[r^*] < J[r_{\text{unif}}]$ whenever $\lambda(t)$ is non-constant ($A_m > 0, \kappa_m > 0$).

#### SymPy Verification Script (`step-35`)
```python
import sympy as sp

t = sp.Symbol("t", real=True)
T = sp.Symbol("T", positive=True)
B = sp.Symbol("B", positive=True)
mu = sp.Symbol("mu", real=True)
lambda_0 = sp.Symbol("lambda_0", positive=True)
A = sp.Symbol("A", positive=True)
kappa = sp.Symbol("kappa", positive=True)
r = sp.Symbol("r", positive=True)
lam = sp.Symbol("lam", positive=True)
nu = sp.Symbol("nu", positive=True)  # Lagrange multiplier
I_sqrt = sp.Symbol("I_sqrt", positive=True)  # int_0^T sqrt(lambda(s)) ds

# 1. Pointwise Lagrangian stationarity and strict convexity
L = lam / (2 * r) + nu * r
dL_dr = sp.diff(L, r)
d2L_dr2 = sp.diff(dL_dr, r)
assert sp.simplify(d2L_dr2 - lam / r**3) == 0
assert d2L_dr2.is_positive is True

r_opt_nu = sp.solve(dL_dr, r)[0]
assert sp.simplify(r_opt_nu - sp.sqrt(lam) / sp.sqrt(2 * nu)) == 0

# 2. Enforce budget constraint int_0^T r*(t) dt = B => I_sqrt / sqrt(2*nu) = B
nu_val = sp.solve(I_sqrt / sp.sqrt(2 * nu) - B, nu)[0]
r_star = sp.simplify(r_opt_nu.subs(nu, nu_val))
assert sp.simplify(r_star - B * sp.sqrt(lam) / I_sqrt) == 0

# 3. Minimum objective J[r*] = (1/(2*B)) * I_sqrt^2
integrand_star = sp.simplify((lam / (2 * r_star)))
assert sp.simplify(integrand_star - sp.sqrt(lam) * I_sqrt / (2 * B)) == 0
J_star = sp.simplify((I_sqrt / (2 * B)) * I_sqrt)
assert sp.simplify(J_star - I_sqrt**2 / (2 * B)) == 0

# 4. Exact Cauchy-Schwarz / Lagrange sum-of-squares proof that J[r*] <= J[r_unif]
l1, l2, l3 = sp.symbols("l1 l2 l3", positive=True)
diff_3 = 3 * (l1 + l2 + l3) - (sp.sqrt(l1) + sp.sqrt(l2) + sp.sqrt(l3)) ** 2
sos_3 = (
    (sp.sqrt(l1) - sp.sqrt(l2)) ** 2
    + (sp.sqrt(l2) - sp.sqrt(l3)) ** 2
    + (sp.sqrt(l3) - sp.sqrt(l1)) ** 2
)
assert sp.simplify(diff_3 - sos_3) == 0
```

---

## 4. Line-by-Line Codebase Audit

### 4.1 `apps/research/harness.py` (Lines 1–420)

| Lines | Symbol / Code | Defect & Mathematical Failure Mode |
| :--- | :--- | :--- |
| `58` | `STOP_WINDOW = 3` | Hardcodes a 3-batch zero-verified lookback window (`_plateau`). Does not track singleton/doubleton incidence frequencies $(Q_1, Q_2)$ or sample coverage $\hat{C}_{\text{GT}}$. |
| `85–88` | `def _plateau(batches: list[BatchSummary]) -> bool:` | Returns `True` whenever `len(batches) >= 3` and `all(b.verified == 0 for b in recent)`. Because query order is shuffled (`rng.shuffle(queries)` at line `356`), 3 consecutive batches of narrow/niche angle queries can return 0 novel verified hosts while earlier batches produced exclusively singletons ($Q_1 \gg Q_2$, so $\hat{C}_{\text{Chao2}} \ll 1$ and $\hat{C}_{\text{GT}} \ll 1$). Conversely, when a small country has $S = 2$ institutions and both are found and recaptured in Batch 0 ($\hat{C}_{\text{Chao2}} = 1.0, \hat{C}_{\text{GT}} = 1.0$), `_plateau` still wastes 3 additional full batches (`3 * batch_size = 30` queries) before stopping! |
| `218`, `281–286`, `417` | `state.recaptured: set[str]`, `run.recaptured = len(state.recaptured)` | `harness.py` meticulously tracks `state.recaptured` (every `RegisterEntry` domain re-discovered by the open-web sweep) and persists `run.recaptured` on `SweepRun`. However, `run.recaptured` ($R$) is **never used** anywhere in `harness.py`, `coverage.py`, or `hybrid_strategy.py` to compute Chapman's mark-recapture population estimate $\hat{N}_{\text{Chapman}} = \frac{(M+1)(C+1)}{R+1} - 1$ or dual-frame coverage $\hat{C}_{\text{Chapman}} = \frac{M + C - R}{\hat{N}_{\text{Chapman}}}$. |
| `237–258` | `_record_discovery(...)` | Appends `hit.provider` to `disc.returned_by` when a known `SweepDiscovery` is hit again (`provider not in disc.returned_by`), but **does not increment a total sighting counter or distinct-query incidence counter** when the *same* provider returns the same host across *multiple distinct queries* (`q_obj.query`). As a result, single-provider sweeps (`providers=("brave",)` at line `73`) always have `len(disc.returned_by) == 1` for every discovery, making provider-only frequency counts blind to multi-query recapture unless distinct query hits are also counted! |

### 4.2 `apps/research/tally.py` (Lines 1–121)

| Lines | Symbol / Code | Defect & Mathematical Failure Mode |
| :--- | :--- | :--- |
| `35–53` | `def found_by(run: SweepRun) -> dict[str, dict[str, int]]:` | Computes `total` and `sole` per provider (`len(by) == 1`), which is the exact provider-level singleton count $Q_{1,p}$, yet never aggregates $Q_1 = \sum_p Q_{1,p}$ and doubletons $Q_2 = |\{d : |\text{returned\_by}(d)| = 2\}|$ to report Chao2 unseen richness $\hat{f}_0$. |
| `56–82` | `def angle_yield(run: SweepRun) -> dict[str, dict[str, int]]:` | Counts `queries`, `Empty`, and `first_finds` (Attributedsolely to `d.first_query_id`), ignoring recapture incidence across angles (`SweepQuery` hits on already-discovered hosts). |
| `104–121` | `def retire_dead_angles(...)` | Retires an angle only after `consecutive_zero_runs >= 3` where `stats["first_finds"] == 0`. Does not expose frequency-of-frequencies $(f_1, f_2, n)$ or coverage metrics on `SweepRun`. |

### 4.3 `apps/research/coverage.py` (Lines 1–469)

| Lines | Symbol / Code | Defect & Mathematical Failure Mode |
| :--- | :--- | :--- |
| `295–302` | `EXHAUSTED_STOPS = frozenset({"saturated", "register_complete", " sweeps_exhausted", "no_sources"})` | Treats `"saturated"` (from `_plateau` in `harness.py`) as unconditionally exhausted even when `SweepRun` stopped with low Chao1/Chapman coverage, and provides no coverage-based stop reason (`"chao1_complete"`, `"chapman_complete"`). |
| `332–341` | `class AreaLine(TypedDict, total=False):` | Exposes `eligible`, `verified_Cycles`, ` thin`, `stop_reason`, and `exhausted`, but omits estimated total richness ($\hat{S}_{\text{Chao1}}$ or $\hat{N}_{\text{Chapman}}$) and estimated coverage $\hat{C} \in (0, 1]$. Downstream consumers (`hybrid_strategy.py` and `tap.py`) are forced to guess saturation from raw `eligible` counts. |

### 4.4 `apps/research/tap.py` (Lines 1–1201)

| Lines | Symbol / Code | Defect & Mathematical Failure Mode |
| :--- | :--- | :--- |
| `601–653` | `def _first_stages(inputs, ...)` | Groups all `coverage` queries (across *all* countries in `inputs.destinations`) into a single stage `0` list, and all `local` queries (across *all* countries) into a single stage `1` list, passing each combined list to a single `_Stage1` instance. |
| `720–722`, `830–836` | `self.window: deque[int] = deque(maxlen=settings.FIRST_SEARCH_PLATEAU_BATCH)` in `_Stage1.__init__` and `ask_all` | **Cross-Country Plateau Contamination Bug**: `self.window` is a **single global deque** across all `SearchRequest` items in the stage. In `render_tap_queries` (`seam_bindings.py:570–596`), requests are generated country-by-country (`for code in inputs.destinations:`). When Country 1 (`inputs.destinations[0]`, e.g., Luxembourg or an already-saturated country) yields `FIRST_SEARCH_PLATEAU_BATCH` (default `5`) consecutive queries with `< FIRST_SEARCH_PLATEAU_MIN_NEW` new hosts, `self.plateaued = full = True` at line `836` **cancels all pending futures and breaks out of `ask_all`**, preventing Country 2, Country 3, etc. from executing a single query! |
| `716`, `785–814` | `self.known_domains`, `new_count` | Tracks `known_domains` globally across the stage without recording per-country sighting counts $n_c$, singletons $f_{1,c}$ (domains seen in only 1 query in country $c$), or doubletons $f_{2,c}$ (domains seen in 2 queries in country $c$). |

### 4.5 `apps/research/hybrid_strategy.py` (Lines 1–703)

| Lines | Symbol / Code | Defect & Mathematical Failure Mode |
| :--- | :--- | :--- |
| `184–190` | `min_programs_per_country: int = 5`, `deep_saturation_count: int = 15` | **Small-Country Impossibility Bug**: Fixed integer thresholds applied uniformly to all 200+ ISO countries. For small countries (`LU`, `MT`, `IS`, `CY`, `LI`, `MC`, `AD`, `SM`, `BN`, `QA`, `BH`, `EE`, `LV`, `SI`, `ME`, `MK`, `AL`, etc.) or specialized degree fields where the true number of programmes in country $c$ is $1 \le S_c < 5$, `effective_prog_count >= 5` (`depth_ok` at line `503`) can **never** be satisfied unless `past_stop` is already set. |
| `495–505` | `min_warm_programs_per_country = 2`, `depth_ok = effective_prog_count >= required_floor` | Even when `past_stop` is `True` (a sweep or tap already ran and exhausted the country), line `496` still enforces `required_floor = 2` (`min_warm_programs_per_country = 2`). If a small country has $S_c = 1$ programme in the student's field (e.g., the sole national university offers 1 Master's in that discipline) and `tehsil_agent` has already found and verified that 1 programme ($\hat{C}_{\text{Chao1}} = 1.0$), `effective_prog_count = 1 < 2` forces `depth_ok = False`, triggering `TIER_3_COLD_CELL_SWEEP` (`unexplored_countries.append(cc)` at line `527`) on **every single run forever**! |
| `507–518` | `exploration_ok = past_stop or (effective_prog_count >= thresholds.deep_saturation_count)` | For any country without `past_stop`, requires `effective_prog_count >= 15` (`deep_saturation_count`) to avoid `TIER_2_TARGETED_DELTA`, even if 4 independent queries have repeatedly recaptured the exact same $S_{\text{obs}} = 4$ programmes with $f_1 = 0$ singletons ($\hat{C}_{\text{Chao1}} = 1.0, \hat{C}_{\text{GT}} = 1.0$). |

### 4.6 `apps/research/cycle_verification.py` & `apps/funding/cycle_schedule.py`

| File & Lines | Symbol / Code | Defect & Mathematical Failure Mode |
| :--- | :--- | :--- |
| `cycle_verification.py:567–577` | `def _years_back(d: date, years: int) -> date:` | Shifts `run.today` backward by `1` and `2` calendar years (`d.replace(year=d.year - years)`). |
| `cycle_verification.py:580–621` | `_DEFINITE_REFUSALS = frozenset({"archive_none", "archive_skew"})`, `def _step_wayback(...)` | **Off-Season Wayback Probe & Permanent Refusal Bug**: `_step_wayback` calls `run.seams.capture_near(url, at=_years_back(run.today, back))`. In `fetch/archive.py:197–200`, if the nearest Wayback snapshot is more than `CYCLE_ARCHIVE_SKEW_DAYS` (default `90` days) away from `run.today - 1 year`, `capture_near` returns `reason="archive_skew:<date>"`. Because `"archive_skew"` is in `_DEFINITE_REFUSALS` (line `580`), `all_definite` is `True` and line `617` calls `run.ledger.mark_looked(key)`—**permanently caching the failure**! Even worse, university and scholarship pages are archived most densely around their **active call opening / deadline window** ($\mu_{\text{open}}, \mu_{\text{close}}$), not during the dead summer/winter off-season when `run.today` happens to fall. Probing at `run.today - k years` during the off-season either hits `archive_skew` or retrieves an off-season snapshot saying "Applications are currently closed", missing the historical call dates that exist in Wayback snapshots from the peak season! |
| `apps/funding/cycle_schedule.py:30–56` | `def next_check(...) -> date:` | Uses a 3-step piecewise constant rule (`7` days within 60 days of deadline, `14` days within $\pm 1$ month of `open_month`, `45` days otherwise). Ignores historical call variance (`past_calls` dispersion $\kappa$), ignores whether a country's intake start provides a prior when `open_month` is unknown, and creates sharp cliff discontinuities at 60 days and month boundaries instead of the optimal $\Delta t^*(t) \propto 1/\sqrt{\lambda(t)}$ renewal schedule. |

### 4.7 `apps/research/fetch/monitor.py` (Lines 1–208)

| Lines | Symbol / Code | Defect & Mathematical Failure Mode |
| :--- | :--- | :--- |
| `28`, `122`, `162` | `MONITOR_CRON = "0 6 1 * *"`, `cron: str = MONITOR_CRON` | Hardcodes a single uniform monthly cron (`1st of every month at 06:00`, $\Delta t = 30.4\text{ days}$, expected detection delay $15.2\text{ days}$) for all monitored scholarship/programme URLs. |
| `118–174` | `def create_monitor(...)` | Does not accept a `cadence` / seasonal hazard specification or compute a seasonally adapted cron expression / polling interval under the `FIRECRAWL_MONTHLY_CREDITS` budget constraint. |

---

## 5. Drop-In Python Algorithmic Specification — Part A: Mark-Recapture & Unseen-Species Stopping

### 5.1 New Module: `apps/research/mark_recapture.py`

Create `/home/orkhan/Desktop/tehsil_agent/apps/research/mark_recapture.py` as a pure, zero-dependency mathematical module implementing the SymPy-verified estimators from **Proposition 1**.

```python
"""Nonparametric species-richness (Chao1/Chao2), Good-Turing sample coverage,
and Chapman mark-recapture estimators for scale-invariant discovery stopping.

References:
- Chao (1984), Scand. J. Stat. 11(4):265-270 (bias-corrected Chao1).
- Chao (1987), Biometrics 43(4):783-791 (Chao2 incidence estimator).
- Good (1953), Biometrika 40(3-4):237-264 (Good-Turing sample coverage).
- Chapman (1951), Univ. Calif. Publ. Stat. 1:131-160 (mark-recapture).
- Chao & Colwell (2017), SORT 41(1):3-54 (coverage-standardized stopping).
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import math
from typing import Iterable


@dataclass(frozen=True)
class RichnessEstimate:
    """Unseen-species and sample-coverage summary for a cell or country."""

    s_obs: int
    n_sightings: int
    f1: int
    f2: int
    s_hat_chao1: float
    unseen_chao1: float
    coverage_chao1: float
    coverage_good_turing: float
    missing_mass_gt: float
    # Optional dual-frame Chapman mark-recapture fields (when a register exists)
    m_register: int = 0
    c_sweep: int = 0
    r_recaptured: int = 0
    n_hat_chapman: float | None = None
    var_chapman: float | None = None
    coverage_chapman: float | None = None

    @property
    def effective_coverage(self) -> float:
        """Conservative scale-invariant coverage in [0, 1].

        Requires corroboration when s_obs >= 1: combines Chao1 completeness
        with Good-Turing sample coverage (and Chapman coverage when available)
        so a single uncorroborated singleton (n=1, f1=1 -> C_GT=0) cannot
        masquerade as 100% coverage.
        """
        if self.s_obs <= 0 or self.n_sightings <= 0:
            return 0.0
        base = min(self.coverage_chao1, self.coverage_good_turing)
        if self.coverage_chapman is not None:
            return max(base, min(self.coverage_chapman, self.coverage_good_turing))
        return base


def chao1_richness(s_obs: int, f1: int, f2: int) -> float:
    """Bias-corrected Chao1 richness estimator (Chao 1984; Chao & Colwell 2017).

    S_hat_Chao1 = S_obs + f1 * (f1 - 1) / (2 * (f2 + 1))

    Satisfies S_hat_Chao1 >= S_obs for all non-negative integers f1, f2,
    with strict inequality iff f1 >= 2.
    """
    if s_obs <= 0:
        return 0.0
    f1_pos = max(0, int(f1))
    f2_pos = max(0, int(f2))
    unseen = (f1_pos * (f1_pos - 1)) / (2.0 * (f2_pos + 1))
    return float(s_obs) + unseen


def chao2_incidence_richness(
    s_obs: int, q1: int, q2: int, n_units: int
) -> float:
    """Bias-corrected Chao2 incidence richness across n_units queries/providers (Chao 1987).

    S_hat_Chao2 = S_obs + ((T - 1) / T) * Q1 * (Q1 - 1) / (2 * (Q2 + 1))
    """
    if s_obs <= 0:
        return 0.0
    if n_units <= 1:
        return chao1_richness(s_obs, q1, q2)
    q1_pos = max(0, int(q1))
    q2_pos = max(0, int(q2))
    scale = (n_units - 1.0) / float(n_units)
    unseen = scale * (q1_pos * (q1_pos - 1)) / (2.0 * (q2_pos + 1))
    return float(s_obs) + unseen


def chao1_coverage(s_obs: int, f1: int, f2: int) -> float:
    """Scale-invariant Chao1 completeness ratio S_obs / S_hat_Chao1 in (0, 1]."""
    if s_obs <= 0:
        return 0.0
    s_hat = chao1_richness(s_obs, f1, f2)
    if s_hat <= 0.0:
        return 0.0
    return min(1.0, max(0.0, float(s_obs) / s_hat))


def good_turing_coverage(f1: int, n_total: int, f2: int = 0) -> float:
    """Good-Turing sample coverage C_hat_GT in [0, 1] (Good 1953; Chao & Jost 2012).

    Uses the Turing-Chao improved coverage estimator when f2 > 0:
        C_hat = 1 - (f1 / n) * ((n - 1) * f1 / ((n - 1) * f1 + 2 * f2))
    which reduces to 1 - f1 / n when f2 == 0 or n <= 1.
    Always satisfies C_hat == 0 when f1 == n (all observations are singletons)
    and C_hat == 1 when f1 == 0 and n >= 1.
    """
    if n_total <= 0:
        return 0.0
    f1_clamped = min(max(0, int(f1)), int(n_total))
    f2_pos = max(0, int(f2))
    if f1_clamped == 0:
        return 1.0
    if f1_clamped >= n_total:
        return 0.0
    if n_total > 1 and f2_pos > 0:
        denom = (n_total - 1) * f1_clamped + 2.0 * f2_pos
        correction = ((n_total - 1) * f1_clamped) / denom if denom > 0 else 1.0
        missing = (f1_clamped / float(n_total)) * correction
    else:
        missing = f1_clamped / float(n_total)
    return min(1.0, max(0.0, 1.0 - missing))


def chapman_estimator(
    m_register: int, c_sweep: int, r_recaptured: int
) -> tuple[float, float]:
    """Chapman (1951) bias-corrected mark-recapture population & variance estimator.

    Args:
        m_register: M >= 0 known entities in authoritative register.
        c_sweep: C >= 0 distinct entities captured in open-web sweep (novel + recaptured).
        r_recaptured: R in [0, min(M, C)] register entities re-discovered in sweep.

    Returns:
        (n_hat_chapman, var_chapman) satisfying:
        n_hat_chapman - (M + C - R) = (M - R)*(C - R)/(R + 1) >= 0.
    """
    m = max(0, int(m_register))
    c = max(0, int(c_sweep))
    r = min(max(0, int(r_recaptured)), min(m, c))
    if m == 0 or c == 0:
        return float(m + c), 0.0
    n_hat = ((m + 1.0) * (c + 1.0)) / (r + 1.0) - 1.0
    var_hat = (
        (m + 1.0)
        * (c + 1.0)
        * (m - r)
        * (c - r)
        / (((r + 1.0) ** 2) * (r + 2.0))
    )
    return n_hat, var_hat


def chapman_coverage(
    m_register: int, c_sweep: int, r_recaptured: int
) -> float | None:
    """Dual-frame coverage |M union C| / N_hat_Chapman in (0, 1]."""
    m = max(0, int(m_register))
    c = max(0, int(c_sweep))
    r = min(max(0, int(r_recaptured)), min(m, c))
    if m <= 0 or c <= 0:
        return None
    union_known = m + c - r
    n_hat, _ = chapman_estimator(m, c, r)
    if n_hat <= 0.0:
        return None
    return min(1.0, max(0.0, float(union_known) / n_hat))


def estimate_from_sightings(
    sighting_counts: Iterable[int],
    *,
    n_units: int = 0,
    m_register: int = 0,
    r_recaptured: int = 0,
) -> RichnessEstimate:
    """Build a RichnessEstimate from per-entity sighting/incidence counts.

    Args:
        sighting_counts: Positive integer count of independent sightings
            (queries or providers) for each observed entity.
        n_units: Number of sampling units (queries/batches) if incidence-based.
        m_register: Authoritative register count M (if a register exists).
        r_recaptured: Recaptured register entities R in the sweep.
    """
    counts = [int(c) for c in sighting_counts if int(c) > 0]
    s_obs = len(counts)
    n_sightings = sum(counts)
    freq = Counter(counts)
    f1 = freq.get(1, 0)
    f2 = freq.get(2, 0)

    if n_units > 1:
        s_hat = chao2_incidence_richness(s_obs, f1, f2, n_units)
    else:
        s_hat = chao1_richness(s_obs, f1, f2)

    cov_chao1 = (float(s_obs) / s_hat) if s_hat > 0 else 0.0
    cov_gt = good_turing_coverage(f1, n_sightings, f2=f2)

    c_sweep = s_obs + max(0, int(r_recaptured))
    n_chap: float | None = None
    v_chap: float | None = None
    cov_chap: float | None = None
    if m_register > 0 and c_sweep > 0:
        n_chap, v_chap = chapman_estimator(m_register, c_sweep, r_recaptured)
        cov_chap = chapman_coverage(m_register, c_sweep, r_recaptured)

    return RichnessEstimate(
        s_obs=s_obs,
        n_sightings=n_sightings,
        f1=f1,
        f2=f2,
        s_hat_chao1=s_hat,
        unseen_chao1=max(0.0, s_hat - s_obs),
        coverage_chao1=cov_chao1,
        coverage_good_turing=cov_gt,
        missing_mass_gt=1.0 - cov_gt,
        m_register=max(0, int(m_register)),
        c_sweep=c_sweep,
        r_recaptured=max(0, int(r_recaptured)),
        n_hat_chapman=n_chap,
        var_chapman=v_chap,
        coverage_chapman=cov_chap,
    )
```

---

### 5.2 Drop-In Integration into `apps/research/harness.py`

In `apps/research/harness.py`:
1. Track per-host query incidence `host_query_hits: dict[str, int]` inside `_RunState` (lines `207–222`) so every distinct query that returns a verified or recaptured host increments its incidence count (fixing the single-provider `returned_by` blindness).
2. Upgrade `_plateau` (lines `85–88`) into `_should_stop_sweep(batches, state, m_register)` combining:
   - **Early Coverage Completion**: If at least `MIN_COVERAGE_BATCHES = 2` batches have run, $S_{\text{obs}} + R \ge 1$, and `est.effective_coverage >= 0.92` with `est.unseen_chao1 < 0.5` (meaning $f_1 \le 1$ and almost all sightings are recaptures), stop immediately as `"saturated"` without burning 3 extra empty batches in small countries.
   - **Coverage-Guarded Plateau**: When the last `STOP_WINDOW = 3` batches have `verified == 0`, check whether `est.missing_mass_gt > 0.50` and `len(batches) < STOP_WINDOW + 2`: if more than half of all sightings so far were singletons ($f_1 / n > 0.5$) and only 3 batches have run, allow up to 2 grace batches before declaring `"saturated"`.

```python
# In apps/research/harness.py

from apps.research.mark_recapture import RichnessEstimate, estimate_from_sightings

STOP_WINDOW = 3
MIN_COVERAGE_BATCHES = 2
SWEEP_COVERAGE_STOP_THRESHOLD = 0.92


@dataclass
class _RunState:
    seen_hosts: set[str]
    known_hosts: dict[str, str]
    register_hosts: set[str]
    recaptured: set[str] = field(default_factory=set)
    verified_hosts: set[str] = field(default_factory=set)
    host_sightings: dict[str, int] = field(default_factory=dict)
    m_register: int = 0
    queries_sent: int = 0
    urls_checked: int = 0
    verified_total: int = 0

    def richness_estimate(self, n_batches: int = 0) -> RichnessEstimate:
        """Compute Chao1/Chao2 + Good-Turing + Chapman estimate for the current sweep."""
        active_hosts = self.verified_hosts | self.recaptured
        counts = [
            self.host_sightings.get(h, 1) for h in active_hosts
        ]
        return estimate_from_sightings(
            counts,
            n_units=max(n_batches, self.queries_sent),
            m_register=self.m_register,
            r_recaptured=len(self.recaptured),
        )


def _plateau(
    batches: list[BatchSummary],
    state: _RunState | None = None,
) -> bool:
    """Stop when 3 consecutive batches yield 0 novel verified hosts, OR when
    mark-recapture / Chao1 + Good-Turing sample coverage proves exhaustion.
    """
    if state is not None and len(batches) >= MIN_COVERAGE_BATCHES:
        est = state.richness_estimate(n_batches=len(batches))
        # Fast stop for small countries (e.g. LU, MT, IS) once all institutions
        # have been found and corroborated across multiple queries (f1 == 0).
        if (
            est.s_obs >= 1
            and est.f1 == 0
            and est.effective_coverage >= SWEEP_COVERAGE_STOP_THRESHOLD
            and batches[-1].verified == 0
        ):
            return True

    if len(batches) < STOP_WINDOW:
        return False
    recent = batches[-STOP_WINDOW:]
    if not all(b.verified == 0 for b in recent):
        return False

    # Guard against premature plateau when singleton missing mass is still > 50%
    if state is not None and len(batches) == STOP_WINDOW:
        est = state.richness_estimate(n_batches=len(batches))
        if est.s_obs >= 3 and est.missing_mass_gt > 0.50:
            return False
    return True
```

Inside `_process_batch` (lines `281–304`), increment `state.host_sightings[host]` on every query hit for both `register_hosts` and `verified_hosts`:
```python
        for hit in hits:
            host = _registrable_host(hit.url)
            if not host:
                continue
            state.host_sightings[host] = state.host_sightings.get(host, 0) + 1
            if host in state.register_hosts:
                state.recaptured.add(host)
                continue
            if host in state.seen_hosts:
                if host in state.verified_hosts:
                    _record_discovery(run, hit, host, q_obj, "verified", "")
                continue
```
And when `state.verified_total += 1` at line `328`, record `state.verified_hosts.add(host)`.

---

### 5.3 Drop-In Integration into `apps/research/tap.py` (Fixing Cross-Country Plateau Contamination)

In `apps/research/tap.py`, `_Stage1` (lines `705–844`) currently uses a single global `self.window: deque[int]` across all countries. When `inputs.destinations` has multiple countries, Country 1's plateau halts the entire loop before Country 2 is ever queried.

Replace the single global deque with **per-country sliding windows and per-country sighting counters** (`self.windows_by_country: dict[str, deque[int]]` and `self.country_host_sightings: dict[str, dict[str, int]]`), so that:
1. A country $c$ plateaus if and only if **its own** queries in `self.windows_by_country[c]` have exhausted new discoveries OR its per-country Chao1 + Good-Turing coverage `est_c.effective_coverage >= 0.90` (with `est_c.f1 == 0` after at least 3 queries).
2. When country $c$ plateaus, only remaining pending queries for **that country $c$** are skipped/cancelled; queries for other destination countries continue undisturbed!
3. The stage as a whole marks `self.plateaued = True` only when **all** destination countries present in the stage have plateaued.

```python
# Drop-in replacement for _Stage1 plateau tracking in apps/research/tap.py (lines 705-844)

from collections import defaultdict, deque
from apps.research.mark_recapture import estimate_from_sightings


class _Stage1:
    """Runs stage-1 search requests with per-country plateau & Chao1/GT coverage isolation."""

    def __init__(
        self,
        *,
        stage_index: int,
        stage_name: str,
        known_domains: set[str],
        seams: TapSeams,
        run: TapRun,
        deadline: float,
    ) -> None:
        self.stage_index = stage_index
        self.stage_name = stage_name
        self.known_domains = known_domains
        self.seams = seams
        self.run = run
        self.deadline = deadline
        self.windows_by_country: dict[str, deque[int]] = defaultdict(
            lambda: deque(maxlen=settings.FIRST_SEARCH_PLATEAU_BATCH)
        )
        self.country_host_sightings: dict[str, dict[str, int]] = defaultdict(dict)
        self.plateaued_countries: set[str] = set()
        self.active_countries: set[str] = set()
        self.queries_by_country: dict[str, int] = defaultdict(int)
        self.Stage_queries = 0
        self.stage_hits = 0
        self.stage_new = 0
        self.timed_out = False
        self.plateaued = False
        self.lock = threading.Lock()

    def _country_key(self, req: SearchRequest) -> str:
        return (req.country or "_GLOBAL_").strip().upper()

    def _is_country_saturated(self, cc: str) -> bool:
        """Check whether country `cc` has reached plateau or Chao1/GT saturation."""
        win = self.windows_by_country[cc]
        if len(win) == win.maxlen and sum(win) < settings.FIRST_SEARCH_PLATEAU_MIN_NEW:
            return True
        # Fast scale-invariant saturation for small countries (1-4 institutions)
        # once >= 3 queries have run and all discovered domains are corroborated (f1 == 0).
        if self.queries_by_country[cc] >= 3:
            sightings = self.country_host_sightings[cc]
            if sightings:
                est = estimate_from_sightings(
                    sightings.values(),
                    n_units=self.queries_by_country[cc],
                )
                if est.s_obs >= 1 and est.f1 == 0 and est.effective_coverage >= 0.90:
                    return True
        return False

    def _ingest_One(
        self, req: SearchRequest, raw_hits: list[SearchHit]
    ) -> tuple[list[SearchHit], bool]:
        cc = self._country_key(req)
        kept: list[SearchHit] = []
        new_count = 0
        with self.lock:
            self.active_countries.add(cc)
            if cc in self.plateaued_countries:
                return [], False
            self.stage_queries += 1
            self.queries_by_country[cc] += 1
            seen_in_query: set[str] = set()
            for h in raw_hits:
                dom = registrable_domain(h.url)
                if not dom:
                    continue
                if is_blocked_domain(
                    dom,
                    blocklist=self.seams.blocklist_domains,
                    patterns=self.seams.blocklist_patterns,
                ):
                    continue
                self.stage_hits += 1
                kept.append(h)
                if dom not in seen_in_query:
                    seen_in_query.add(dom)
                    cc_map = self.country_host_sightings[cc]
                    cc_map[dom] = cc_map.get(dom, 0) + 1
                if dom not in self.known_domains:
                    self.known_domains.add(dom)
                    new_count += 1
                    self.stage_new += 1

            self.windows_by_country[cc].append(new_count)
            if self._is_country_saturated(cc):
                self.plateaued_countries.add(cc)
            all_saturated = bool(self.active_countries) and (
                self.plateaued_countries >= self.active_countries
            )
            return kept, all_saturated
```

And in `_Stage1.ask_all` (lines `816–844`), pre-populate `self.active_countries = {self._country_key(r) for r in requests}` before submitting futures, and inside the worker/completion loop skip any request whose country is already in `self.plateaued_countries`, breaking out of `ask_all` only when `all_saturated` (`self.plateaued_countries >= self.active_countries`) is `True`.

---

### 5.4 Drop-In Integration into `apps/research/coverage.py` and `apps/research/hybrid_strategy.py` (Fixing Small-Country Impossibility)

#### 5.4.1 Enrich `AreaLine` in `apps/research/coverage.py`
In `apps/research/coverage.py` (lines `332–375`), compute and attach `estimated_total` ($\hat{S}_{\text{Chao1}}$ or $\hat{N}_{\text{Chapman}}$) and `estimated_coverage` ($\hat{C} \in [0, 1]$) on every `AreaLine`:

```python
# In apps/research/coverage.py

class AreaLine(TypedDict, total=False):
    rung: int
    field: str
    degree_level: str
    country: str
    eligible: int
    verified_cycles: int
    thin: bool
    stop_reason: str
    exhausted: bool
    clause: str
    estimated_total: float
    estimated_coverage: float
```

Helper function `_area_coverage_metrics(cell: CellCoverage) -> tuple[float, float]` in `apps/research/coverage.py`:
```python
def _area_coverage_metrics(cell: CellCoverage) -> tuple[float, float]:
    """Compute (estimated_total, estimated_coverage) for a CellCoverage row
    using SweepRun discoveries + RegisterEntry mark-recapture when available.
    """
    from apps.research.mark_recapture import estimate_from_sightings
    from apps.research.models import RegisterEntry, SweepDiscovery, SweepRun

    latest_run = (
        SweepRun.objects.filter(
            country=cell.country,
            rung=cell.rung,
        )
        .order_by("-started_at")
        .first()
    )
    if latest_run is None:
        if cell.stop_reason in EXHAUSTED_STOPS and cell.eligible_count > 0:
            return float(cell.eligible_count), 1.0
        return float(cell.eligible_count), 0.0

    # Sighting counts across providers (and queries) for verified discoveries
    discoveries = list(
        SweepDiscovery.objects.filter(
            first_run=latest_run,
            status=SweepDiscovery.Status.VERIFIED,
        ).only("returned_by")
    )
    sighting_counts = [max(1, len(d.returned_by or [])) for d in discoveries]
    if not sighting_counts and cell.eligible_count > 0:
        sighting_counts = [2] * cell.eligible_count

    m_reg = 0
    if latest_run.register_id:
        m_reg = (
            RegisterEntry.objects.filter(
                register_id=latest_run.register_id,
                organisation__isnull=False,
            )
            .values("organisation")
            .distinct()
            .count()
        )

    est = estimate_from_sightings(
        sighting_counts,
        n_units=max(1, latest_run.queries_sent),
        m_register=m_reg,
        r_recaptured=latest_run.recaptured,
    )
    total_est = (
        est.n_hat_chapman
        if est.n_hat_chapman is not None
        else max(float(cell.eligible_count), est.s_hat_chao1)
    )
    return round(total_est, 2), round(est.effective_coverage, 4)
```

#### 5.4.2 Replace Fixed Count Floors with Scale-Invariant Coverage in `apps/research/hybrid_strategy.py`
In `apps/research/hybrid_strategy.py`:
1. Add `min_coverage_ratio: float = 0.85` to `SufficiencyThresholds` (line `184`).
2. Extract `country_coverage_ratios: dict[str, float]` from `cov_snapshot.get("areas", [])` (lines `407–428`).
3. Update `depth_ok` and `exploration_ok` (lines `495–520`) so a country `cc` satisfies both `depth_ok` and `exploration_ok` whenever **either**:
   - Its scale-invariant Chao1 / Chapman / Good-Turing coverage satisfies `cov_ratio >= thresholds.min_coverage_ratio` (`0.85`) with `effective_prog_count >= 1`, **or**
   - `past_stop` is `True` and `effective_prog_count >= 1` (fixing the `min_warm_programs_per_country = 2` bug for single-programme countries like `LU` or `MT`), **or**
   - `effective_prog_count >= thresholds.min_programs_per_country` (preserving the existing fast-path for large countries before a sweep finishes).

```python
# Drop-in replacement in apps/research/hybrid_strategy.py (lines 184-212 and 492-534)

@dataclass(frozen=True)
class SufficiencyThresholds:
    """Configurable thresholds for deciding DB sufficiency."""

    min_programs_per_country: int = 5
    deep_saturation_count: int = 15
    min_coverage_ratio: float = 0.85
    min_scholarships_Total: int = 3
    min_verified_ratio: float = 0.6
    max_staleness_days: int = 90
    max_deadline_horizon_days: int = 365
    tier2_max_queries: int = 8
    tier2_timeout_s: float = 20.0
    tier3_max_queries: int = 25
    tier3_timeout_s: float = 45.0
```

And inside `plan_hybrid_retrieval` (lines `492–534`):
```python
        cov_ratio = country_coverage_ratios.get(cc, 0.0)
        coverage_complete = (
            effective_prog_count >= 1
            and cov_ratio >= thresholds.min_coverage_ratio
        )

        # When a country has already reached an exhausted stop_reason or
        # scale-invariant Chao1/Chapman coverage >= 0.85, even S_obs = 1
        # verified programme in a small country (e.g. LU, MT, IS) is complete.
        if past_stop or coverage_complete:
            required_floor = 1
        else:
            required_floor = thresholds.min_programs_per_country

        depth_ok = effective_prog_count >= required_floor

        # Exploration completeness: satisfied if a prior sweep/tap stopped,
        # OR scale-invariant coverage >= 0.85, OR absolute count >= 15.
        exploration_ok = (
            past_stop
            or coverage_complete
            or (effective_prog_count >= thresholds.deep_saturation_count)
        )
```

---

## 6. Drop-In Python Algorithmic Specification — Part B: Seasonal Renewal Hazard Probing & Dynamic Monitor Scheduling

### 6.1 Mathematical Model of the Seasonal Funding Renewal Hazard

Let day-of-year $t \in [0, T)$ with $T = 365.25$. A scholarship or university intake cycle has two primary seasonal state-change events each year:
1. **Call Opening ($\mu_{\text{open}}$)**: When the new cycle's call text and application portal go live.
2. **Application Deadline ($\mu_{\text{close}}$)**: When the deadline passes or is extended/updated.

Using the circular von Mises (wrapped normal) renewal hazard from **Proposition 2**:
$$\lambda(t) = \lambda_0 + A_{\text{open}} \exp\!\left(\kappa_{\text{open}} \cos\!\left(\frac{2\pi(t - \mu_{\text{open}})}{T}\right)\right) + A_{\text{close}} \exp\!\left(\kappa_{\text{close}} \cos\!\left(\frac{2\pi(t - \mu_{\text{close}})}{T}\right)\right),$$
where:
- $\mu_{\text{open}}$ is inferred from:
  1. `cadence.open_month` (if known on `FundingCadence`),
  2. Circular mean of `past_calls[k].open_date` (or `past_calls[k].deadline - 90 days`) in `CycleEvidence`,
  3. Country academic calendar intake prior: `default_intake_start_for_country(country, year) - 180 days` (from `apps/funding/validity.py:217`, since scholarship/admission calls typically open 5–7 months before intake start).
- Concentration $\kappa_{\text{open}} \in [1.5, 6.0]$ measures phase certainty ($\kappa = 4.0$ when `open_month` or $\ge 2$ consistent `past_calls` exist, $\kappa = 2.0$ when inferred from country intake start).
- By **Proposition 2**, the optimal polling rate is $r^*(t) = B \frac{\sqrt{\lambda(t)}}{\int_0^T \sqrt{\lambda(s)}\,ds}$, and the optimal inter-check interval on date $d$ is:
  $$\Delta t^*(d) = \text{clip}\!\left(\text{round}\!\left(\frac{\int_0^T \sqrt{\lambda(s)}\,ds}{B\,\sqrt{\lambda(t(d))}}\right), \; \Delta t_{\min}, \; \Delta t_{\max}\right).$$

---

### 6.2 Drop-In Upgrade to `apps/funding/cycle_schedule.py`

Extend `/home/orkhan/Desktop/tehsil_agent/apps/funding/cycle_schedule.py` with the continuous square-root seasonal renewal hazard scheduler while preserving complete backward compatibility with existing callers of `next_check`:

```python
"""Compute next_check dates and Wayback probe targets via seasonal renewal hazard.

Implements Proposition 2 (Cho & Garcia-Molina 2003; Wolf et al. 2002):
polling rate r*(t) proportional to sqrt(lambda(t)) minimizes expected
call-opening and deadline detection delay under a fixed annual check budget B.
"""

from __future__ import annotations

from datetime import date, timedelta
import math
from typing import Iterable, Sequence

from django.conf import settings


_DAYS_IN_YEAR = 365.25
_INTEGRATION_STEPS = 73  # 5-day quadrature grid over 365 days


def _day_of_year(d: date) -> float:
    return float(d.timetuple().tm_yday)


def _month_center_doy(month: int) -> float:
    """Day-of-year for the 15th of a given month (1..12)."""
    m = min(12, max(1, int(month)))
    return float(date(2025, m, 15).timetuple().tm_yday)


def circular_mean_doy(dates: Iterable[date]) -> tuple[float | None, float]:
    """Compute the circular mean day-of-year and von Mises concentration kappa
    from historical call opening or deadline dates.
    """
    angles = [2.0 * math.pi * (_day_of_year(d) / _DAYS_IN_YEAR) for d in dates]
    if not angles:
        return None, 0.0
    sin_sum = sum(math.sin(a) for a in angles)
    cos_sum = sum(math.cos(a) for a in angles)
    n = float(len(angles))
    r_bar = math.hypot(sin_sum, cos_sum) / n
    mean_angle = math.atan2(sin_sum, cos_sum)
    if mean_angle < 0:
        mean_angle += 2.0 * math.pi
    mean_doy = (mean_angle / (2.0 * math.pi)) * _DAYS_IN_YEAR
    # High concentration when historical dates cluster tightly
    if len(angles) == 1:
        kappa = 3.0
    else:
        kappa = min(6.0, max(1.5, 1.0 / max(0.15, 1.0 - r_bar)))
    return mean_doy, kappa


def seasonal_hazard(
    doy: float,
    *,
    open_doy: float | None = None,
    deadline_doy: float | None = None,
    kappa_open: float = 3.5,
    kappa_deadline: float = 4.5,
    lambda_base: float = 1.0,
    amp_open: float = 2.5,
    amp_deadline: float = 4.0,
) -> float:
    """Evaluate the non-homogeneous seasonal renewal hazard lambda(t) > 0 at day-of-year `doy`."""
    lam = float(lambda_base)
    if open_doy is not None:
        phase = 2.0 * math.pi * (doy - open_doy) / _DAYS_IN_YEAR
        lam += amp_open * math.exp(kappa_open * (math.cos(phase) - 1.0)) * math.exp(2.0)
    if deadline_doy is not None:
        phase = 2.0 * math.pi * (doy - deadline_doy) / _DAYS_IN_YEAR
        lam += amp_deadline * math.exp(kappa_deadline * (math.cos(phase) - 1.0)) * math.exp(2.5)
    return max(1e-6, lam)


def next_check(
    *,
    today: date,
    deadline: date | None,
    open_month: int | None,
    is_rolling: bool = False,
    past_open_dates: Sequence[date] = (),
    past_deadlines: Sequence[date] = (),
    annual_budget_checks: float | None = None,
) -> date:
    """Return the date when this cycle record should next be re-verified.

    Preserves exact deadline-window and open-month bounds configured in Django
    settings while interpolating smoothly via the optimal square-root renewal
    hazard schedule r*(t) = B * sqrt(lambda(t)) / int sqrt(lambda(s)) ds.
    """
    default_days = int(getattr(settings, "CYCLE_CHECK_DAYS_DEFAULT", 45))
    season_days = int(getattr(settings, "CYCLE_CHECK_DAYS_SEASON", 14))
    deadline_days = int(getattr(settings, "CYCLE_CHECK_DAYS_DEADLINE", 7))
    window = int(getattr(settings, "CYCLE_DEADLINE_WINDOW_DAYS", 60))

    if is_rolling and deadline is None and open_month is None and not past_open_dates:
        return today + timedelta(days=default_days)

    # 1. Immediate proximity to an active upcoming deadline takes highest priority
    if deadline is not None:
        delta = (deadline - today).days
        if 0 <= delta <= window:
            return today + timedelta(days=deadline_days)

    # 2. Immediate proximity to a known open_month (within +/- 1 calendar month)
    if open_month is not None:
        diff = (today.month - open_month) % 12
        if diff in (0, 1, 11):
            return today + timedelta(days=season_days)

    # 3. Continuous square-root seasonal hazard schedule when historical dates or
    #    open_month / deadline phases exist
    open_doy: float | None = None
    kappa_open = 3.5
    if open_month is not None:
        open_doy = _month_center_doy(open_month)
    elif past_open_dates:
        open_doy, kappa_open = circular_mean_doy(past_open_dates)

    deadline_doy: float | None = None
    kappa_deadline = 4.5
    if deadline is not None:
        deadline_doy = _day_of_year(deadline)
    elif past_deadlines:
        deadline_doy, kappa_deadline = circular_mean_doy(past_deadlines)

    if open_doy is None and deadline_doy is None:
        return today + timedelta(days=default_days)

    # Quadrature of int_0^T sqrt(lambda(s)) ds
    dt_grid = _DAYS_IN_YEAR / _INTEGRATION_STEPS
    integral_sqrt = 0.0
    for i in range(_INTEGRATION_STEPS):
        s = (i + 0.5) * dt_grid
        integral_sqrt += math.sqrt(
            seasonal_hazard(
                s,
                open_doy=open_doy,
                deadline_doy=deadline_doy,
                kappa_open=kappa_open,
                kappa_deadline=kappa_deadline,
            )
        ) * dt_grid

    # Calibrate annual budget B so off-season checks respect default_days
    budget = annual_budget_checks or (_DAYS_IN_YEAR / float(default_days)) * 1.65
    lam_today = seasonal_hazard(
        _day_of_year(today),
        open_doy=open_doy,
        deadline_doy=deadline_doy,
        kappa_open=kappa_open,
        kappa_deadline=kappa_deadline,
    )
    r_star = budget * math.sqrt(lam_today) / integral_sqrt
    optimal_days = int(round(1.0 / max(r_star, 1.0 / default_days)))
    clamped_days = max(deadline_days, min(default_days, optimal_days))
    return today + timedelta(days=clamped_days)
```

---

### 6.3 Drop-In Upgrade to `apps/research/cycle_verification.py`: Hazard-Guided Wayback Target Dates

In `apps/research/cycle_verification.py`, Step `1b` (`_step_wayback`, lines `583–621`) currently probes `at = _years_back(run.today, back)`, which anchors Wayback CDX lookups to the arbitrary wall-clock date `run.today` and treats `"archive_skew"` as a permanent `_DEFINITE_REFUSALS` (`mark_looked`).

Replace `_step_wayback` target selection with `_wayback_probe_dates(subject, stored, today, years_back)` which anchors historical archive probes at the **peak seasonal call-opening / active-window phase** $\mu_{\text{open}}^{(Y-k)}$ for each prior year $Y - k$, and removes `"archive_skew"` from `_DEFINITE_REFUSALS` when an off-season probe misses the active call window:

```python
# Drop-in replacement in apps/research/cycle_verification.py (lines 567-621)

from apps.funding.validity import default_intake_start_for_country


def _seasonal_anchor_months(
    subject: _Subject,
    stored: list[_StoredEntry],
    today: date,
) -> list[int]:
    """Return up to 2 prioritized calendar months (1..12) when the funding call
    is most likely active on the page (peak renewal hazard), falling back to
    country intake-start minus 5 months, and finally `today.month`.
    """
    months: list[int] = []

    def _add(m: int | None) -> None:
        if m is not None and 1 <= m <= 12 and m not in months:
            months.append(m)

    # 1. Explicit cadence open_month on the Scholarship / Program
    if subject.cadence and subject.cadence.open_month:
        _add(subject.cadence.open_month)

    # 2. Historical open_date or (deadline - 2 months) from stored CycleEvidence
    for entry in stored:
        ev = entry.evidence
        if ev.open_date:
            _add(ev.open_date.month)
        if ev.deadline:
            # 1-2 months before deadline is inside the active call window
            _add(((ev.deadline.month - 2) % 12) + 1)
        for pc in ev.past_calls:
            if pc.open_date:
                _add(pc.open_date.month)
            elif pc.deadline:
                _add(((pc.deadline.month - 2) % 12) + 1)

    # 3. Country academic intake calendar prior (5 months before intake start)
    if not months and subject.country:
        intake_start = default_intake_start_for_country(subject.country, today.year)
        _add(((intake_start.month - 6) % 12) + 1)

    # 4. Always include today.month as a fallback anchor
    _add(today.month)
    return months[:2]


def _wayback_target_dates(
    subject: _Subject,
    stored: list[_StoredEntry],
    today: date,
    years_back: int,
) -> list[date]:
    """Generate hazard-guided Wayback target dates across `years_back` prior years."""
    anchor_months = _seasonal_anchor_months(subject, stored, today)
    targets: list[date] = []
    for back in range(1, years_back + 1):
        target_year = today.year - back
        for m in anchor_months:
            day = min(today.day, 28) if m == today.month else 15
            candidate = date(target_year, m, day)
            if candidate < today and candidate not in targets:
                targets.append(candidate)
    return targets


# Do NOT treat "archive_skew" as a permanent definite refusal that locks out
# future seasonal probes; only "archive_none" (zero snapshots in CDX at all)
# is a definite refusal for the URL.
_DEFINITE_REFUSALS = frozenset({"archive_none"})
```

Inside `_step_wayback` (lines `589–615`), iterate over `for at in _wayback_target_dates(subject, stored, run.today, years_back):` instead of `for back in range(1, years_back + 1): at = _years_back(run.today, back)`.

---

### 6.4 Drop-In Upgrade to `apps/research/fetch/monitor.py`: Seasonal Hazard Cron Scheduling

In `apps/research/fetch/monitor.py`, add `seasonal_monitor_cron(today, open_month=..., deadline=...)` so `create_monitor` dynamically selects a cron schedule proportional to $\sqrt{\lambda(t)}$ under the `FIRECRAWL_MONTHLY_CREDITS` budget:
- **Peak Deadline / Call-Opening Hazard Window** ($\lambda(t) / \lambda_0 \ge 4.0$, within $\pm 1$ month of `open_month` or $\le 60$ days before `deadline`): weekly polling `"0 6 * * 1"` ($\Delta t = 7\text{ days}$).
- **Shoulder Season** ($1.8 \le \lambda(t) / \lambda_0 < 4.0$, $1\text{--}2$ months before `open_month`): biweekly polling `"0 6 1,15 * *"` ($\Delta t \approx 15\text{ days}$).
- **Off-Season Baseline** ($\lambda(t) / \lambda_0 < 1.8$): monthly/bimonthly baseline `"0 6 1 * *"`.

```python
# Addition to apps/research/fetch/monitor.py

from datetime import date
from apps.funding.cycle_schedule import _day_of_year, _month_center_doy, seasonal_hazard

MONITOR_CRON = "0 6 1 * *"
MONITOR_CRON_BIWEEKLY = "0 6 1,15 * *"
MONITOR_CRON_WEEKLY = "0 6 * * 1"


def seasonal_monitor_cron(
    *,
    today: date | None = None,
    open_month: int | None = None,
    deadline: date | None = None,
) -> str:
    """Select a Firecrawl cron schedule scaled to sqrt(lambda(t)) (Proposition 2)."""
    if open_month is None and deadline is None:
        return MONITOR_CRON
    ref = today or date.today()
    open_doy = _month_center_doy(open_month) if open_month is not None else None
    deadline_doy = _day_of_year(deadline) if deadline is not None else None
    lam = seasonal_hazard(
        _day_of_year(ref),
        open_doy=open_doy,
        deadline_doy=deadline_doy,
    )
    ratio = math.sqrt(lam)
    if ratio >= 2.2:
        return MONITOR_CRON_WEEKLY
    if ratio >= 1.35:
        return MONITOR_CRON_BIWEEKLY
    return MONITOR_CRON
```

---

## 7. Verification Plan & Property-Based Test Suite

When implementing this specification, add unit and property-based tests in `apps/research/tests/test_mark_recapture_and_scheduling.py` verifying that real new outputs feed into real callers (`plan_hybrid_retrieval`, `_Stage1.ask_all`, `_plateau`, `_step_wayback`, and `next_check`):

1. **`test_small_country_reaches_tier1_db_complete`**:
   - Construct a country `LU` with $S = 1$ programme (`effective_prog_count = 1`) and a `SweepRun` / `AreaLine` with $S_{\text{obs}} = 1, f_1 = 0, f_2 = 1$ (`estimated_coverage = 1.0`).
   - Pass into `plan_hybrid_retrieval`: assert `plan.tier == RetrievalTier.TIER_1_DB_COMPLETE` and `"LU" not in plan.unexplored_countries` (whereas previously `effective_prog_count < 5` and `effective_prog_count < 2` forced `TIER_3_COLD_CELL_SWEEP`).
2. **`test_tap_stage1_per_country_plateau_isolation`**:
   - Feed `_Stage1.ask_all` 5 zero-new queries for `country="LU"` followed by 3 novel-domain queries for `country="DE"`.
   - Assert `"LU" in stage.plateaued_countries`, `"DE"` queries still execute and discover all 3 novel domains, and `stage.stage_new == 3` (whereas previously the global `self.window` aborted before `"DE"` ran a single query).
3. **`test_chapman_and_chao1_algebraic_invariants`**:
   - Assert $\hat{S}_{\text{Chao1}} \ge S_{\text{obs}}$ with strict inequality iff $f_1 \ge 2$, $\hat{N}_{\text{Chapman}} - (M + C - R) = \frac{(M-R)(C-R)}{R+1} \ge 0$, $\hat{N}_{\text{Chapman}}(R=C) = M$, and $\hat{C}_{\text{GT}}(f_1=n) = 0$.
4. **`test_wayback_probes_peak_season_instead_of_offseason_today`**:
   - Run `_step_wayback` with `run.today = date(2026, 7, 15)` (off-season) on a subject with `cadence.open_month = 11`.
   - Assert `seams.capture_near` is called with `at = date(2025, 11, 15)` and `date(2024, 11, 15)` first, and that an `archive_skew` response does not permanently mark the ledger key `LOOKED`.
5. **`test_square_root_hazard_next_check_monotone_in_hazard`**:
   - Verify `next_check` returns strictly shorter intervals as `today` approaches `open_month` or `deadline`, bounded within `[CYCLE_CHECK_DAYS_DEADLINE, CYCLE_CHECK_DAYS_DEFAULT]`.
