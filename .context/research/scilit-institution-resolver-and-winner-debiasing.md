# Universal Institutional Name Resolution & Horvitz-Thompson / Empirical-Bayes LinkedIn Winner De-Biasing

- **scilit Ask Run ID:** `20261103T193153Z-8bf5ddce` (`--profile argon --no-agent --quick`, 231 papers consulted, 60 scored, 32 accepted)
- **scilit Prove Verification:** `PROVED` (`fuzz_verified=True`, `sympy_verified=True`, `antigravity/argon`)
- **Target Modules:** `apps/research/vocabulary.py`, `apps/research/names.py`, `apps/research/resolver.py`, `apps/research/winner_scraper.py`

---

## 1. Literature Synthesis (`scilit ask` Run `20261103T193153Z-8bf5ddce`)

### 1.1 Selection Bias in Observational Social-Media & LinkedIn Career Cohorts
Social media and professional networking platforms generate observational cohorts through self-selection—requiring internet access, platform availability, account creation, and active self-reporting of educational and career milestones (Iacus et al., 2017; CARMA 2018 `10.4995/carma2018.2018.8302`; Astuti, Bank of Italy `10.48550/arxiv.2212.09813`). Unweighted sample means from such cohorts suffer from severe coverage and self-reporting bias across two primary dimensions:
1. **Country-level platform penetration $p_{\text{country}}(c_i)$:** High-penetration English and Western European labor markets (`US`, `GB`, `CA`, `AU`, `NL`, `IE`, `SG`, `SE`) exhibit $65\text{--}85\%$ workforce LinkedIn coverage, whereas East Asian, Central Asian, or platform-restricted markets (`JP`, `KR`, `CN`, `UZ`, `KZ`, `VN`) exhibit $10\text{--}28\%$ coverage.
2. **Discipline-level self-reporting propensity $p_{\text{field}}(d_i)$:** Business, finance, software engineering, and data science cohorts maintain detailed LinkedIn profiles at high rates ($80\text{--}95\%$), whereas humanities, fine arts, agriculture, and clinical medicine graduates report at significantly lower rates ($40\text{--}55\%$).

### 1.2 Horvitz-Thompson, Stabilized Hájek IPW, and Empirical-Bayes Post-Stratification (MRP)
- **Horvitz-Thompson & Pseudo-Weighting:** In probability sampling, Horvitz and Thompson (1952) weight each observation $i$ by the inverse of its inclusion probability $\pi_i$. For non-probability digital trace samples where true inclusion probabilities are unknown, quasi-randomization / Propensity Score-based Inverse Probability Weighting (PS-IPW; Deville & Särndal, 1992; Schonlau & Couper, 2017; Arletti et al., 2025 `10.3389/fpos.2025.1592589`) estimates $\hat{\pi}_i = \max(\pi_{\min}, p_{\text{platform}}(c_i, d_i))$ with truncation floor $\pi_{\min} > 0$ to bound weight variance.
- **Stabilized Hájek Estimator:** Replacing the population size $N$ with the sum of inverse-propensity weights $W = \sum_{i=1}^n w_i$ ($w_i = 1 / \hat{\pi}_i$) yields the location- and scale-invariant Hájek estimator (Hájek, 1971):
  $$\hat{\mu}_{\text{Hajek}}(y) = \frac{\sum_{i=1}^n (y_i / \hat{\pi}_i)}{\sum_{i=1}^n (1 / \hat{\pi}_i)} = \frac{\sum_{i=1}^n w_i y_i}{\sum_{i=1}^n w_i}$$
- **Kish's Effective Sample Size & Multilevel Regression with Post-Stratification (MRP):** Unequal weights inflate sampling variance by the Kish design effect $D_{\text{eff}} = n / n_{\text{eff}}$, reducing the effective sample size to:
  $$n_{\text{eff}} = \frac{\left(\sum_{i=1}^n w_i\right)^2}{\sum_{i=1}^n w_i^2}$$
  Following Gelman & Little (1997), Wang et al. (2015), and Astuti (`10.48550/arxiv.2212.09813`), combining the IPW/cell estimate with a hierarchical prior mean $\mu_0$ via Empirical Bayes shrinkage weight $\lambda(n_{\text{eff}}) = \frac{n_{\text{eff}}}{n_{\text{eff}} + \kappa}$ ($\kappa > 0$) prevents noisy small-$n_{\text{eff}}$ cohorts from dominating downstream student recommendations:
  $$\hat{\mu}_{\text{EB}} = \lambda(n_{\text{eff}}) \hat{\mu}_{\text{Hajek}} + \bigl(1 - \lambda(n_{\text{eff}})\bigr) \mu_0$$

### 1.3 Cross-Lingual Institutional Record Linkage without Per-Country Static Dictionaries
In probabilistic record linkage (Fellegi & Sunter, 1969) and hybrid token-similarity models such as SoftTFIDF (Cohen, Ravikumar & Fienberg, 2003; Moreau et al., 2008; NEMO, 2010; OpenOrgs, 2023), institutional names are decomposed into:
1. **Organizational kind tokens ($K$):** Low-IDF structural class markers (`University`, `Stiftung`, `Fondation`, `Fundación`, `Stichting`, `Yayasan`, `Vakfı`, `대학`, `大学`) that must agree in institutional class (`KIND`) between query and candidate homepage title, whether realized as independent tokens, head-initial compounds (`fondation...`, `fundacion...`, `stichting...`, `yayasan...`), or tail compounds (`...stiftung`, `...universität`).
2. **Geographic & generic modifiers ($G \cup C$):** Country names, CLDR city/timezone/territory labels, and high-frequency organizational modifiers (`national`, `research`, `science`, `education`) that carry zero identifying log-odds on their own (preventing directory sites like `stiftungen.org` or `embassies.info` from matching specific bodies).
3. **Distinctive proper-noun tokens ($D$):** High-IDF stems scored via language-aware symmetric transliteration (`fold`) that normalizes German ASCII umlaut digraphs (`hoer -> hor`) without corrupting Romance/Dutch vowel sequences (`puerto`, `maestro`, `oeuvre`, `boekman`).

---

## 2. Formal Theorem & Symbolic Proof (`scilit prove --profile argon`)

### Theorem (Kish's Effective Sample Size Bounds & Empirical-Bayes Monotonicity)
For any sample size $n \ge 1$, propensity clipping floor $\pi_{\min} > 0$, platform propensities $p_i \in (0, 1]$, and inverse-propensity weights $w_i = 1 / \max(\pi_{\min}, p_i) > 0$ ($i = 1, \dots, n$), Kish's effective sample size
$$n_{\text{eff}} = \frac{\left(\sum_{i=1}^n w_i\right)^2}{\sum_{i=1}^n w_i^2}$$
satisfies:
1. $0 < 1 \le n_{\text{eff}} \le n$, with upper equality $n_{\text{eff}} = n$ if and only if $w_1 = w_2 = \dots = w_n$.
2. For any prior concentration $\kappa > 0$, the Empirical Bayes shrinkage weight $\lambda(n_{\text{eff}}) = \frac{n_{\text{eff}}}{n_{\text{eff}} + \kappa}$ is strictly increasing in $n_{\text{eff}}$ on $(0, n]$ and bounded in $\left(0, \frac{n}{n + \kappa}\right]$.

### Proof (Verified by SymPy & Counterexample Fuzzing)
1. **Positivity and Lower Bound:** Since $\pi_{\min} > 0$ and $p_i > 0$, every $w_i > 0$. By expansion,
   $$\left(\sum_{i=1}^n w_i\right)^2 - \sum_{i=1}^n w_i^2 = 2 \sum_{1 \le i < j \le n} w_i w_j \ge 0 \implies n_{\text{eff}} \ge 1 > 0.$$
2. **Upper Bound and Equality Condition (Lagrange / Cauchy-Schwarz Identity):**
   By Lagrange's identity,
   $$n \sum_{i=1}^n w_i^2 - \left(\sum_{i=1}^n w_i\right)^2 = \sum_{1 \le i < j \le n} (w_i - w_j)^2 \ge 0.$$
   Dividing by $\sum_{i=1}^n w_i^2 > 0$ yields
   $$n - n_{\text{eff}} = \frac{\sum_{1 \le i < j \le n} (w_i - w_j)^2}{\sum_{i=1}^n w_i^2} \ge 0 \implies n_{\text{eff}} \le n.$$
   Because a sum of real squares vanishes if and only if each summand vanishes, $n - n_{\text{eff}} = 0 \iff w_i = w_j$ for all $1 \le i < j \le n$.
3. **Strict Monotonicity of Empirical Bayes Shrinkage:**
   For $\kappa > 0$ and $0 < x_1 < x_2 \le n$,
   $$\lambda(x_2) - \lambda(x_1) = \frac{\kappa (x_2 - x_1)}{(x_1 + \kappa)(x_2 + \kappa)} > 0, \quad \frac{d\lambda}{dx} = \frac{\kappa}{(x + \kappa)^2} > 0,$$
   establishing $0 < \lambda(n_{\text{eff}}) \le \frac{n}{n + \kappa} < 1$. $\blacksquare$

---

## 3. Implementation Specification

### 3.1 `apps/research/vocabulary.py` & `apps/research/resolver.py`
- Preserve `load_vocabulary(cc)` raising `VocabularyMissing` when `resolver_data/{CC}.json` or `kinds.json` is absent or stale (preserving all existing unit tests in `tests/research/test_vocabulary.py`).
- Add `universal_vocabulary_for(cc)` and `load_or_build_vocabulary(cc)` in `apps/research/vocabulary.py`:
  - Synthesizes `Vocabulary` for any valid ISO 3166-1 alpha-2 country code (`GB, US, FR, NL, IT, ES, CH, SE, CA, AU, JP, KR, PL, LU, MT, IS, LI, MC, AD, SM`, etc.) from:
    - CLDR official/de-facto languages (`babel.languages.get_official_languages`, `get_territory_language_info`),
    - CLDR localized territory names and IANA timezone city names (`babel.Locale`, `babel.core.get_global("territory_zones")`),
    - `kind_words.py` (`load_kind_words()` across all languages) + `kinds.json` + baseline Wikidata organization class QIDs,
    - `domains.py` (`CATALOGUE_DOMAINS` / `_NATIONAL_CATALOGUES` place stems and ccTLD mappings including `GB -> uk`).
- Scale `_GEO_FLOOR` and `_ORG_FLOOR` proportionally in `build_country_doc` for microstates (`LU, MT, IS, LI, MC, AD, SM`).
- Wire `load_or_build_vocabulary` into `apps/research/resolver.py` (`Resolver` accepts `vocabulary: Vocabulary | str | None = None` and provides `Resolver.for_country(country_code, ...)`).

### 3.2 `apps/research/names.py`
- Update `fold(text)` so German ASCII umlaut digraph normalization (`ae -> a`, `oe -> o`, `ue -> u`) preserves French `oeu` (`oeuvre`, `coeur`), Dutch `oe` stems (`boekman`, `onderzoek`, `stichting` contexts), `[qg]ue` (`que`, `guerra`), and Romance `ue`/`ae` stems (`puerto`, `maestro`, `bueno`, `nuevo`, `escuela`), while maintaining `fold("Kind Hörstiftung") == fold("kind hoerstiftung") == "kind horstiftung"`.
- Update `_morph_kinds(token, vocab)` to recognize both tail compounds (`...stiftung`, `...universität`) and head-initial compounds (`fondation...`, `fundacion...`, `stichting...`, `yayasan...`, `fondazione...`, `universite...`, `universidad...`), as well as cross-lingual institutional stems against the vocabulary's canonical organization QIDs.

### 3.3 `apps/research/winner_scraper.py`
- Expand `_RESEARCH_SIGNAL_RE` and `_normalize_degree_level` to cover multilingual research roles/publications and Master's/Bachelor's/PhD degree titles (`M.Sc.`, `M.A.`, `Magister`, `Master`, `Laurea Magistrale`, `Diplôme d'Ingénieur`, `Máster`, `Mestrado`, `Yüksek Lisans`, `Magistr`, `Магистр`, `修士`, `硕士`, `석사`, etc.).
- Add `WinnerArchetype` dataclass and `build_winner_archetype` (aliased as `aggregate_winner_archetype`) implementing:
  - Clipped country $\times$ discipline $\times$ degree-level LinkedIn reporting propensities $\pi_i = \max(\pi_{\min}, p_{\text{platform}}(c_i, d_i))$,
  - Stabilized Hájek inverse-propensity weighted means (`avg_gpa`, `avg_work_months`, `research_share`) and prior-university/country/field/level shares (`top_prior_universities`),
  - Kish's effective sample size `effective_sample_size` ($n_{\text{eff}} = (\sum w_i)^2 / \sum w_i^2$),
  - Empirical Bayes shrinkage (`shrinkage_factor = n_eff / (n_eff + kappa)`, `eb_avg_gpa`, `eb_avg_work_months`, `eb_research_share`, and optional direct shrinkage when `prior_concentration > 0`).
