# Scilit Deep-Research Audit: Citation Verification, Retraction/Predatory Screening & Faculty–Student Research Fit

**Date:** 2026-11-03  
**Target Area:** High-ROI Target 4 — `apps/documents/evidence/publication.py` (+ `facts.py`, `intake.py`, `ingestion.py`, `verification.py`) and `apps/documents/research_fit/` (`papers.py`, `service.py`, `anchors.py`, `classify.py`, `judge.py`, `pages.py`, `split.py`, `home_context.py`)  
**Reference Codebase:** `/home/orkhan/code/scilit` (`src/scilit/verify/citations.py`, `src/scilit/acquire/hygiene.py`, `src/scilit/background/{identify,profile,topics,run,render}.py`, `src/scilit/discover/{semantic,rerank,cocitation}.py`, `src/scilit/discover/sources/doaj.py`, `src/scilit/models.py`)  
**Literature Run Provenance:** `scilit ask` run `20261102T231929Z-25d8396c` (`/home/orkhan/.scilit/runs/20261102T231929Z-25d8396c/`), profile `argon` (`Gemini 4 Argon (High)` / `antigravity/argon` for `planner`, `judge`, `summary`; `st-BAAI/bge-base-en-v1.5` embeddings; `--domain general --no-agent --quick`).

---

## 1. Executive Summary & `scilit` Run Provenance

### 1.1 Headline Findings

1. **Unverified CV Publication Claims & Zero Chimeric/Hijacked Citation Detection (`apps/documents/ingestion.py`, `apps/documents/evidence/publication.py`, `apps/documents/verification.py`)**:
   - When a student uploads a CV in `tehsil_agent`, `ingest_uploaded_cv()` (`apps/documents/ingestion.py:269-623`) extracts `PublicationEntry` records via an LLM into `VerifiedFact(category=FactCategory.PUBLICATION, source_tier=SourceTier.STUDENT_STATEMENT)` and never queries Crossref, OpenAlex, arXiv, or the DOI Handle API. Once confirmed by the student in the UI, a fabricated, chimeric (real DOI pointing to someone else's paper or a different title), or hijacked (real paper where the student is not an author) publication enters the confirmed ledger and is rendered into generated CVs and motivation/referee letters.
   - Even when `fetch_publication()` (`apps/documents/evidence/publication.py:98-124`) is invoked manually via `manage.py ingest_evidence --source <doi>`, it resolves only Crossref + OpenAlex by DOI, does **not** verify that the student's claimed title or authorship matches the resolved DOI (`chimeric` check), does **not** support title-based registry verification when a CV entry lacks a DOI, does **not** route `10.48550/arXiv.*` DOIs to the arXiv Atom API or DataCite DOIs to the DOI Handle API (`https://doi.org/api/handles/{doi}`), and rejects preprints (`posted-content`, `preprint`) with `UnusablePublication` (`apps/documents/evidence/facts.py:41-81`) even when Crossref `relation.is-preprint-of` links the preprint to its published journal article.
   - By porting `scilit`'s deterministic 2-tier verification engine (`src/scilit/verify/citations.py:43-351, 916-1178`) and Crossref/OpenAlex hygiene inspector (`src/scilit/acquire/hygiene.py:16-75, 173-200`), `tehsil_agent` gains zero-LLM-cost detection of **non-existent DOIs**, **chimeric citations** (`title_matches` via `rapidfuzz.fuzz.token_sort_ratio >= 90` + author surname overlap + `|year_claimed - year_registry| <= 1`), **authorship hijacking** (checking `known_owner_names(student)` against normalized registry author surnames while preserving `self_author_index` disambiguation when co-authors share a surname), **retractions and expressions of concern** (`is_retracted`, `update-to`, `updated-by`), **preprint-to-published upgrades** (`is-preprint-of`), and **advisory venue quality flags** (`in_doaj`, `is_core`).

2. **Lexical-Only Faculty–Student Research Alignment & Static Windowing (`apps/documents/research_fit/papers.py`, `service.py`)**:
   - `tehsil_agent`'s faculty paper matcher (`apps/documents/research_fit/papers.py:207-225, 261-379`) searches OpenAlex using `search.title_and_abstract=topic` (`per-page=15`) and scores candidate papers purely by exact token overlap (`len(w) >= 4`) between `topic`/`profile_terms` and `{title} {abstract}`, plus a flat `+1` bonus for any paper published within `_RECENT_BONUS_YEARS = 3` and a binary `"lead"` role check (`author_position in {"first", "last"} or is_corresponding`).
   - Primary literature from our `scilit` run proves three structural failure modes in this design:
     1. **Lexical mismatch across sub-fields**: Student CV terminology (e.g., course projects or thesis titles) rarely shares exact surface tokens with a faculty member's recent specialist terminology; combining lexical search with OpenAlex's 4-level hierarchical topic tree (`domain -> field -> subfield -> topic`) and dense scientific embeddings via Reciprocal Rank Fusion (`rrf_order`, $1/(k + \text{rank})$) significantly outperforms lexical or single-vector retrieval alone (Mandikal & Mooney 2024, `10.48550/arxiv.2401.04055`; Šamárek & Martínek 2026; Bintang & Nurhaida 2026, `10.33395/sinkron.v10i3.16208`).
     2. **"Topic Is Not Agenda" & Career Topic Drift**: Yoo (2026, `10.48550/arxiv.2605.07158`) demonstrates on 3.58M papers that even state-of-the-art embeddings achieve 45–52% precision at broad sub-field (`L1`) but only 15–21% at specific research agenda (`L2`) without citation-graph and topic-drift grounding. A professor's career topic counts are dominated by legacy papers they no longer actively supervise. `scilit`'s `src/scilit/background/topics.py::recency_shift` (`recent_share - career_share` over OpenAlex `primary_topic.id` comparing the last 4 years against career totals) directly separates **emerging research agendas** (`shift > 0`) from **abandoned legacy topics** (`shift < 0`).
     3. **First-Author Student vs. Last/Corresponding Faculty Supervisor Confusion**: In `apps/documents/research_fit/papers.py:148-158, 546-550`, `_author_role()` treats `"first"` and `"last"` authors identically as `"lead"`, and `discover_literature_person_on_page()` accepts any person on a page with a `"lead"` paper—meaning a PhD student or postdoc listed on a lab page who is `"first"` author on one recent paper can be selected as the applicant's prospective faculty supervisor. Resolving the faculty member to an OpenAlex Author ID (`src/scilit/background/identify.py::resolve_identifier`) and distinguishing **PI/supervisory roles** (`last` / `is_corresponding` in lab-sciences, or alphabetical byline conventions in math/economics) from **student first-author roles** eliminates false supervisor matches.

3. **Full Compliance with `tehsil_agent` Commercial Licensing Rules**:
   - Per `docs/research/2026-10-14-cv-publication-and-repo-sources.md` (`L7-9, 41-49`), `tehsil_agent` is a commercial service and **must not** call the ORCID Public API (non-commercial only) or use Semantic Scholar as a bibliographic authority (CC BY-NC + elided abstracts + merged-version year errors).
   - Every `scilit` component recommended for direct porting in Section 4 (`verify/citations.py`, `acquire/hygiene.py`, `background/identify.py`, `background/profile.py`, `background/topics.py`, `background/run.py`) uses **exclusively CC0 / open-commercial endpoints**: **Crossref REST API**, **OpenAlex REST API** (including OpenAlex's CC0 `https://api.openalex.org/authors/https://orcid.org/{orcid}` resolver), **arXiv Atom API**, **DOI Handle API** (`https://doi.org/api/handles/{doi}`), and **DOAJ CC0 metadata**.

---

### 1.2 `scilit` Run Provenance (`20261102T231929Z-25d8396c`)

- **Command Executed:**
  ```bash
  CUDA_VISIBLE_DEVICES="" SCILIT_PROFILE=argon SCILIT_NO_AGENT=1 \
    /home/orkhan/code/scilit/.venv/bin/scilit ask \
    "What bibliometric, semantic-embedding (SPECTER2, SciNCL, OpenAlex concept trees), and automated citation-verification methods best measure student-advisor research alignment and detect chimeric, retracted, or predatory publications in academic CV verification?" \
    --profile argon --domain general --no-agent --quick
  ```
- **Run ID & Artifact Path:** `20261102T231929Z-25d8396c` (`/home/orkhan/.scilit/runs/20261102T231929Z-25d8396c/report.json`, `report.md`, `discovery.json`, `draft.json`, `papers/manifest.csv`)
- **Model Profile (`argon`):**
  - `planner`: `antigravity/argon` (`Gemini 4 Argon (High)`)
  - `judge`: `antigravity/argon` (`Gemini 4 Argon (High)`)
  - `summary`: `antigravity/argon` (`Gemini 4 Argon (High)`)
  - `embedding`: `st-BAAI/bge-base-en-v1.5` + `BAAI/bge-reranker-base` cross-encoder reranker
- **Funnel Metrics:**
  - **Consulted:** 249 unique scholarly works across 6 query channels (`keyword`, `literal`, `expanded`, `neutral-1`, `neutral-2`, `neutral-3`) via OpenAlex and Semantic Scholar discovery
  - **Scored by `antigravity/argon` LLM Judge:** 120 candidates (`judge_tokens: 109,595`)
  - **Accepted (`relevance >= 2`):** 43 papers (7 scored `3/3`, 36 scored `2/3`)
  - **Fetched & Read into Corpus (`papers/`):** 8 top-ranked works (5 full-text PDFs + 3 abstract/snippet records)

#### Table 1: Primary Literature Corpus from `scilit` Run `20261102T231929Z-25d8396c`

| Score | Year | DOI / Identifier | Authors | Title | Sub-Problem Addressed |
| :---: | :---: | :--- | :--- | :--- | :--- |
| **3** | 2026 | `10.33395/sinkron.v10i3.16208` | Bintang & Nurhaida | *Semantic Embedding and Profile-Based Ranking for Automated Reviewer Recommendation* | SPECTER2 + BERT + Reciprocal Rank Fusion (RRF) + OpenAlex frequency, $h$-index, and recency profile signals (NDCG@10 = 0.2621 vs. SPECTER2-only and BM25) |
| **3** | 2026 | `10.48550/arxiv.2605.07158` | Yoo | *Topic Is Not Agenda: A Citation-Community Audit of Text Embeddings* | Audits SPECTER2, Gemini, Qwen3 over 3.58M papers: embeddings reach 45–52% top-10 at subfield (L1) but collapse to 15–21% at research agenda (L2); hybrid lexical + citation reranking reaches 59.6% |
| **3** | 2026 | OpenAlex / APNet (2026) | Šamárek & Martínek | *A Semantic Approach to the Academic Publishing Network: Document Vector Representations and Hybrid Structural-Semantic Fusion over OpenAlex Data* | Late fusion of L2-normalized SPECTER2 (`allenai/specter2_base` + proximity adapter) vectors keyed by OpenAlex ID with bibliographic coupling and OpenAlex topic taxonomy |
| **3** | 2024 | `10.1002/leap.1600` | Dunford, Rosenblum & Hunter | *Using automated analysis of the bibliography to detect potential research integrity issues* | Automated detection of retracted articles, predatory publishers, and AI-generated chimeric citations across submission/production workflows |
| **3** | 2025 | `10.48550/arxiv.2511.04683` | Janse van Rensburg | *AI-Powered Citation Auditing: A Zero-Assumption Protocol for Systematic Reference Verification in Academic Research* | Zero-assumption multi-registry verification protocol audited on 30 academic documents (2,581 references); <0.5% false-positive rate detecting fabricated, orphan, retracted, and predatory citations |
| **3** | 2026 | `10.1002/asi.70104` | Han, Manoharan, Ye & Speidel | *Phantom citations: An empirical study of non-existent and unverifiable references in scholarly literature* | Empirical audit of 3,201 peer-reviewed papers (2023–2025): 2.16% (69 papers) contain unverifiable/phantom references; taxonomy of string, database, and fuzzy-matching verifiers |
| **3** | 2026 | `10.48550/arxiv.2607.09774` | Neralla, Lee, Romero & Choudhary | *Hallucination Detector: A hybrid LLM and Semantic Scholar tool calling for detecting hallucination in scientific literature on AtomGPT.org* | Per-field analysis of hallucinated citations in NeurIPS 2025 papers: author-list mismatch is the strongest discriminator of chimeric/hallucinated references, whereas title/venue similarity alone produces false negatives |
| **2** | 2021 | `10.1371/journal.pone.0244641` | Albert, Dutta, Lin et al. | *ReCiter: An open source, identity-driven, authorship prediction algorithm optimized for academic institutions* | Identity-driven authorship verification using institutional metadata (known name variants, degree years, department, co-authors, grants) to disambiguate homonyms on CVs |
| **2** | 2026 | `10.21203/rs.3.rs-10578122/v1` | Andersen & Ni | *A human-validated procedure for linking PhD dissertation metadata to OpenAlex author profiles* | Linking student thesis/dissertation metadata to OpenAlex author profiles using character-level name matching + transformer/topical similarity |
| **2** | 2026 | `10.48550/arxiv.2608.07254` | Raimondi, Lu, Grun et al. | *SCALE: Scientific Concept Aggregation via LLMs and Embeddings for Fine-Grained Taxonomy Extension* | Extending OpenAlex's 4-level topic hierarchy (`domain -> field -> subfield -> topic`) with fine-grained scientific concepts |
| **2** | 2025 | `10.48550/arxiv.2508.13394` | Do, Nguyen, Li et al. | *CASPER: Concept-integrated Sparse Representation for Scientific Retrieval* | Combining token-level and concept/keyphrase-level representations on SciRepEval to bridge lexical and conceptual matching |
| **2** | 2024 | `10.48550/arxiv.2401.04055` | Mandikal & Mooney | *Sparse Meets Dense: A Hybrid Approach to Enhance Scientific Document Retrieval* | Demonstrates that hybrid sparse (BM25/TF-IDF) + dense (SPECTER2) retrieval significantly beats either sparse or SPECTER2 alone |
| **2** | 2024 | `10.1007/978-3-031-65794-8_16` | Wolff, Seidlmayer & Förstner | *Enriched BERT Embeddings for Scholarly Publication Classification* | Comparative benchmark of SPECTER2, SciNCL, and SciBERT enriched with OpenAlex and Crossref metadata on 123 research fields |
| **2** | 2026 | `10.1145/3844135.3845864` | Beyer & Lingsch-Rosenfeld | *doi-checker: A Tool for Validating References of Research Papers* | Crossref + DataCite reference validation specifically targeting chimeric references (valid DOIs pointing to a different paper or inconsistent authors/year) |
| **2** | 2026 | `10.5281/zenodo.20511184` | Kondratyeva | *bib-verify: Catch hallucinated and AI-generated citations in BibTeX files* | Crossref + OpenAlex + arXiv + PubMed verifier detecting identifier hijacking (valid DOI -> wrong paper), fake co-author lists, and entry-type confusion |
| **2** | 2026 | `10.5281/zenodo.20963060` | Whitlock | *VeraCite: a deterministic auditor for BibTeX/biblatex bibliographies* | Deterministic record-comparison auditor against Crossref, arXiv, OpenAlex ("every finding is a deterministic rule or a comparison against a record, never a language-model guess") |
| **2** | 2026 | `10.5281/zenodo.23274732` | Nissanka | *VERIDEX: Reference Validation and Provenance Auditing against Crossref and OpenAlex* | Dual-registry Crossref + OpenAlex reference validation with persistent provenance ledger |
| **2** | 2026 | `10.48550/arxiv.2605.27700` | Khajavi, Sadeghi, Adhikari & Tessier | *CiteCheck: Retrieval-Grounded Detection of LLM Citation Hallucinations in Scientific Text* | Retrieval-grounded detection of corrupted/chimeric metadata vs. non-existent references |
| **2** | 2026 | `10.48550/arxiv.2604.08501` | Samsonau | *sciwrite-lint: Verification Infrastructure for the Age of Science Vibe-Writing* | Automated verification of reference existence, metadata accuracy, and retraction status against public registries |
| **2** | 2025 | `10.1109/jcdl67857.2025.00023` | Di Scala, Cabanac, Fraisier & Tournier | *Screening Crossref for integrity issues: Massive and longitudinal mining of publication metadata* | Longitudinal mining of Crossref metadata (173M DOIs) for retraction notices, sneaky metadata modifications, and integrity anomalies |
| **2** | 2025 | `10.1007/s11192-025-05524-7` | Haupka | *Presenting a classifier to improve the identification of research journal publications in OpenAlex* | Distinguishing true peer-reviewed research articles from paratext, editorials, letters, and abstracts in OpenAlex metadata |
| **2** | 2026 | `10.48550/arxiv.2601.10431` | Florath | *Aletheia-Probe: A Tool for Automated Journal Assessment* | Open-source journal assessment aggregating curated whitelists/blacklists (DOAJ, ISSN, retraction rates) with explicit conflict reporting |
| **2** | 2019 | `10.1128/mbio.00411-19` | Strinzel, Severin, Milzow & Egger | *Blacklists and Whitelists To Tackle Predatory Publishing: a Cross-Sectional Comparison and Thematic Analysis* | Cross-sectional audit showing substantial overlap and grey-zone ambiguity between blacklists (Cabells/Beall) and whitelists (DOAJ/JSTAGE) |
| **2** | 2020 | `10.18352/lq.10339` | Dony, Raskinet, Renaville et al. | *How reliable and useful is Cabell's Blacklist? A data-driven analysis* | Empirical evaluation of Cabells Predatory Reports vs. DOAJ and Gray OA datasets; demonstrates why binary blacklists must not silently drop works without human review |
| **2** | 2026 | `10.24041/ejmr.2026.1` | Ahmad | *Scholarly Mirage: Predatory Publishing and Scientific Integrity Erosion* | How rapid-acceptance predatory venues distort CV bibliometrics in recruitment and admissions |
| **2** | 2020 | `10.17646/kome.75672.52` | Teixeira da Silva, Dobránszki, Al-Khatib & Tsigaris | *Curriculum vitae: challenges and potential solutions* | Taxonomy of CV misrepresentations (fabricated works, authorship inflation, predatory venues, unverified preprints claimed as published) |

---

## 2. Primary-Source Literature Synthesis

### 2.1 Measuring Student–Advisor Research Alignment: Beyond Lexical Overlap

#### A. Why Pure Lexical Matching Fails and Why Single-Vector Cosine Similarity Stops at Sub-Field (`L1`)
In `tehsil_agent`, faculty-student alignment currently relies on exact token overlap (`len(w) >= 4`) between student/programme topic strings and paper titles/abstracts (`apps/documents/research_fit/papers.py:207-225`). The literature establishes two fundamental results:

1. **Citation-Informed Embeddings (SPECTER2, SciNCL) vs. Lexical Baseline**:
   - Šamárek & Martínek (2026) and Wolff et al. (2024, `10.1007/978-3-031-65794-8_16`) show that citation-informed transformers (`allenai/specter2_base` with proximity adapter, and `malteos/scincl`) encode cross-terminology conceptual proximity learned from the citation graph, agreeing with expert OpenAlex topic taxonomies substantially better than TF-IDF or token overlap when students and faculty use different phrasing for the same methodology.
   - However, Mandikal & Mooney (2024, `10.48550/arxiv.2401.04055`) and Do et al. (2025, `10.48550/arxiv.2508.13394`, `CASPER`) demonstrate that dense embeddings alone struggle with exact domain entities (named algorithms, specific organisms, isotopes, or clinical cohorts). Hybrid retrieval combining sparse lexical/concept matching with dense embeddings consistently outperforms either alone.

2. **"Topic Is Not Agenda" (`10.48550/arxiv.2605.07158`)**:
   - Yoo (2026, `10.48550/arxiv.2605.07158`) audited four state-of-the-art embedding models (including SPECTER2 and Gemini) on an augmented citation graph of **3.58 million scientific papers** partitioned into broad sub-fields (`L1`) and specific research agendas (`L2`).
   - While embeddings achieve **45–52% top-10 precision at the sub-field level (`L1`)**, they collapse to **15–21% top-10 precision at the specific research-agenda level (`L2`)**—meaning **8 out of 10 embedding-nearest neighbors do not share the researcher's actual research agenda**.
   - Conversely, combining lexical/expanded retrieval with structural citation/topic signals raised top-1 `L2` agenda accuracy to **59.6%** (+20.3 percentage points over BM25 and +9.0 percentage points over the best dense embedding retriever).

3. **Reciprocal Rank Fusion (RRF) + Temporal Topic Drift (`recency_shift`)**:
   - Bintang & Nurhaida (2026, `10.33395/sinkron.v10i3.16208`) evaluated researcher-profile alignment on the Stelmakh/OpenReview benchmark and an OpenAlex dataset, showing that **Reciprocal Rank Fusion (RRF)** of dense semantic retrieval with profile-level OpenAlex signals (**topic frequency**, **recency**, and **author role**) achieved the highest `NDCG@10 = 0.2621`, outperforming SPECTER2-only, BERT-only, BM25, and TF-IDF.
   - Crucially, faculty research agendas shift over 3–5 year grant cycles. A professor whose career profile has 40 papers on Topic A (published 2010–2020) and 6 papers on Topic B (published 2023–2026) has a negative recency shift on Topic A and a strong positive recency shift on Topic B. `scilit`'s `src/scilit/background/topics.py::recency_shift` (`recent_share - career_share` over OpenAlex's 4-level topic hierarchy `domain -> field -> subfield -> topic`) directly measures this drift so `tehsil_agent` does not anchor a student's motivation letter to a topic the professor abandoned years ago.

4. **Identity-Driven Disambiguation and Byline Supervision Signals (`ReCiter`, `10.1371/journal.pone.0244641`)**:
   - Albert et al. (2021, `10.1371/journal.pone.0244641`, `ReCiter`) and Andersen & Ni (2026, `10.21203/rs.3.rs-10578122/v1`) show that matching researchers by surname + initial (`"M. Kaya"`) produces high homonym collision rates in institutional directories. Resolve the researcher first via OpenAlex's institution-scoped Author API (`filter=affiliations.institution.id:{inst_id}` or `last_known_institutions.id`) and distinguish **supervisory senior authorship** (`author_position == "last"` or `is_corresponding == True`) from **trainee authorship** (`author_position == "first"` without senior/corresponding history) when discovering prospective supervisors on department pages.

---

### 2.2 Automated Citation Verification, Chimeric Detection, Retraction & Predatory Screening

#### A. Prevalence and Anatomy of Unverifiable & Chimeric Citations
- **Empirical Base Rates**: Han et al. (2026, `10.1002/asi.70104`) audited **3,201 peer-reviewed papers** (2023–2025) and found that **2.16% (69 papers)** contained at least one completely phantom or unverifiable reference. Janse van Rensburg (2025, `10.48550/arxiv.2511.04683`) audited 2,581 references across 30 academic works (undergraduate projects, master's/doctoral theses, and published papers) and documented a ~20% metadata error rate in manual bibliographies, achieving a **<0.5% false-positive rate** using a zero-assumption multi-registry verification protocol.
- **Why DOI Lookup Alone Fails ("Chimeric Citations" / "Identifier Hijacking")**:
  - Dunford, Rosenblum & Hunter (2024, `10.1002/leap.1600`), Beyer & Lingsch-Rosenfeld (2026, `10.1145/3844135.3845864`, `doi-checker`), Kondratyeva (2026, `10.5281/zenodo.20511184`, `bib-verify`), and Whitlock (2026, `10.5281/zenodo.20963060`, `VeraCite`) identify **chimeric citations** (also called **composite citations** or **identifier hijacking**) as the primary failure mode of naive DOI resolvers:
    1. **DOI-to-Title Chimeras**: The citation includes a syntactically valid, resolving DOI (e.g., `10.1038/...`), capability checks pass HTTP 200, and naive code marks it verified—even though the DOI actually points to an unrelated paper, a book review, or a conference front-matter page.
    2. **Title-to-Author Chimeras (Authorship Hijacking / Fabrication)**: Neralla et al. (2026, `10.48550/arxiv.2607.09774`) analyzed confirmed hallucinated citations from NeurIPS 2025 submissions and proved that **author-list mismatch is the single strongest discriminator**: fabricated or hijacked entries frequently pair a real or plausible title and venue with an altered author list or year (`|year_claimed - year_registry| > 1`).
    3. **Non-Article Paratext Inflation**: Haupka (2025, `10.1007/s11192-025-05524-7`) and Teixeira da Silva et al. (2020, `10.17646/kome.75672.52`) show that CV entries sometimes cite conference abstracts, errata, book reviews, or editorial letters as full peer-reviewed journal articles, or list unreviewed preprints as published journal papers.

#### B. Retraction & Expression-of-Concern Screening
- Di Scala et al. (2025, `10.1109/jcdl67857.2025.00023`) and Samsonau (2026, `10.48550/arxiv.2604.08501`, `sciwrite-lint`) emphasize that retraction status is recorded asymmetrically across Crossref and OpenAlex:
  - In **Crossref**, retraction notices and expressions of concern appear in **two directions**: `message.update-to` (on the update notice pointing to the original paper) and `message.updated-by` (Crossmark metadata on the original paper pointing to the retraction/correction notice), with `type` values including `retraction`, `partial_retraction`, `withdrawal`, `removal`, `expression_of_concern`, `correction`, `corrigendum`, `erratum`.
  - In **OpenAlex**, `is_retracted: bool` is a top-level boolean on the work object.
  - Checking **both** Crossref (`update-to` + `updated-by`) and OpenAlex (`is_retracted`), exactly as implemented in `scilit/src/scilit/acquire/hygiene.py:16-59` and `scilit/src/scilit/verify/citations.py:116-120, 168`, catches retractions that either registry alone lags on.

#### C. Predatory & Gray-Zone Venue Screening: Why Whitelist Signals Must Be Advisory, Never Auto-Reject
- Strinzel et al. (2019, `10.1128/mbio.00411-19`), Dony et al. (2020, `10.18352/lq.10339`), Alvarado-de la Barrera et al. (2023, `10.24875/ric.23000191`), and Florath (2026, `10.48550/arxiv.2601.10431`, `Aletheia-Probe`) establish that:
  1. Paywalled blacklists (e.g., Cabells) and discontinued static lists (Beall's list) suffer from false positives on legitimate regional/emerging-economy journals (especially relevant for `tehsil_agent`'s Azerbaijani, Turkish, and Eastern European student cohort) and licensing restrictions.
  2. Conversely, positive whitelist indexing signals embedded directly in OpenAlex CC0 `primary_location.source` (`is_in_doaj: bool` from the Directory of Open Access Journals, and `is_core: bool` from CWTS Leiden Core Sources) plus Crossref/ISSN registration provide transparent, auditable provenance (`scilit/src/scilit/acquire/hygiene.py::source_labels`, `L173-200`).
  3. Consistent with `tehsil_agent`'s `.claude/rules/cv-and-letters.md` (*"Rule strength: Hard rules come from primary institutional sources... Advisory rules come from consensus recruiter and faculty guidance; the verifier warns, never silently drops"*), `is_retracted=True` or `chimeric=True` (author/title mismatch) should trigger a **binding verification hold / downgraded status**, whereas `"not in DOAJ or CORE"` should surface an **advisory review note** rather than silently dropping a student's regional journal article.

---

## 3. Side-by-Side Architectural Comparison: `scilit` vs. `tehsil_agent`

### 3.1 Part 1: Student Publication & Citation Verification (`apps/documents/evidence/publication.py` & `facts.py` vs. `scilit/verify/citations.py` & `acquire/hygiene.py`)

| Capability / Failure Mode | `tehsil_agent` Current Implementation | `scilit` Implementation (`verify/citations.py`, `acquire/hygiene.py`) | Impact on `tehsil_agent` CV & Letter Pipeline |
| :--- | :--- | :--- | :--- |
| **Trigger during CV upload (`ingest_uploaded_cv`)** | `apps/documents/ingestion.py:454-466`: Extracts `PublicationEntry` via LLM into `STUDENT_STATEMENT` ledger row. **Never calls `fetch_publication` or any registry API.** | `verify_references_online()` (`citations.py:984-1178`): Automatically audits every bibliography/publication entry against Crossref + OpenAlex + arXiv + Handle API using `ThreadPoolExecutor(max_workers=8)`. | Students (or LLM extraction errors) can introduce hallucinated, mistitled, or hijacked publications that pass into confirmed `VerifiedFact` rows unchecked. |
| **Lookup without a DOI (Title + Author + Year)** | **Not supported.** `publication.py:98` (`fetch_publication(doi_or_url)`) requires a `10.xxxx/...` DOI regex match (`_DOI_RE`). | `_search_title_in_registries()` (`citations.py:916-981`): Tier-2 fallback searches OpenAlex (`?search=<title>&per-page=5`) and Crossref (`?query.bibliographic=<title>&rows=3`) and validates title + author + year. | Many student CVs list real papers without a printed DOI string; `tehsil_agent` currently cannot verify or enrich them with their canonical DOI/venue/authors. |
| **arXiv (`10.48550/arXiv.*` or `arXiv:YYMM.NNNNN`) & DataCite DOIs** | Queries only Crossref and OpenAlex (`publication.py:109-110`). `10.48550/arXiv.*` returns 404 on Crossref; DataCite DOIs missing from OpenAlex fail with `PublicationNotFound`. | `_check_one()` (`citations.py:276-315`): Routes `10.48550/arxiv.*` directly to `_arxiv()` (`export.arxiv.org/api/query`, `L172-199`) and falls back to `_handle()` (`https://doi.org/api/handles/{doi}`, `L318-351`) when Crossref/OpenAlex 404. | Directly fulfills `docs/research/2026-10-14-cv-publication-and-repo-sources.md` recommendation ("Send DataCite DOIs to DataCite, and arXiv IDs to the arXiv API"). |
| **Chimeric Citation Detection (Valid DOI -> Wrong Title / Wrong Year)** | **None.** If a student provides a valid DOI (or `ingest_evidence --source <doi>` is called), `publication.py` blindly accepts whatever paper that DOI resolves to. | `_judge()` (`citations.py:202-273`): Computes `rapidfuzz.fuzz.token_sort_ratio(claimed_title, registry_title) >= 90` (plus unbroken 4+ token subtitle containment `title_matches`, `L59-74`) and `abs(claimed_year - reg_year) <= 1`. Sets `chimeric=True` on mismatch. | Prevents a valid DOI for Paper B from being attached to Claimed Paper A on a student's CV. |
| **Authorship Hijacking & `self_author_index` Verification** | `apps/documents/evidence/facts.py:84-99` (`_find_owner_index`): Compares `known_owner_names(student)` by exact lowercase token overlap (`_name_tokens(author) == tokens or tokens < _name_tokens(author)`). Does not strip diacritics (`NFKD`) and does not handle homonym co-authors (`self_author_index`). | `_surname()` (`citations.py:76-88`): Normalizes Unicode diacritics via `unicodedata.normalize("NFKD", ...)` and compares surname tokens across all registry authors (`reg_all_surnames`). | Essential for Azerbaijani/Turkish names (`Əliyev`/`Aliyev`, `Şahin`/`Sahin`, `Öztürk`/`Ozturk`) where Crossref/OpenAlex deposits ASCII vs. diacritic forms. |
| **Retraction & Expression of Concern Detection** | **None.** `publication.py:49-95` ignores `update-to`, `updated-by`, and `is_retracted`. A retracted paper is marked `PublicationStatus.PUBLISHED` with `SourceTier.AUTHORITATIVE_DOCUMENT`. | `hygiene.py:16-59` (`crossref_facts`) + `citations.py:116-120, 168`: Checks Crossref `update-to` and `updated-by` against `RETRACTION_TYPES` (`retraction`, `partial_retraction`, `withdrawal`, `removal`) and `NOTE_TYPES` (`expression_of_concern`, `correction`, `corrigendum`, `erratum`) plus OpenAlex `is_retracted`. | Prevents `tehsil_agent` from showcasing a retracted paper as a flagship achievement in a student's CV or motivation letter. |
| **Preprint Handling & Preprint-to-Published Resolution** | `apps/documents/evidence/facts.py:41-81`: Hard-rejects any `work_type` not in `{"journal-article", "proceedings-article", "book-chapter", "article"}` by raising `UnusablePublication`. All bioRxiv, medRxiv, SSRN, Research Square (`posted-content` / `preprint`) DOIs fail! | `hygiene.py:43-50, 66-75` (`crossref_facts`): Checks Crossref `relation.is-preprint-of` to automatically upgrade a preprint DOI to its peer-reviewed journal DOI (`preprint_of`), and `citations.py:126, 167, 198` sets `preprint=True` when still a preprint. | Instead of crashing with `UnusablePublication`, a preprint with `is-preprint-of` upgrades to the published journal article (`PUBLISHED`), while an unmerged preprint is ingested cleanly or flagged with explicit preprint provenance. |
| **Venue Indexing / Predatory Advisory Signal** | **None.** Extracts only `venue` display string (`publication.py:55, 86`). | `hygiene.py:173-200` (`source_labels`) & `semantic.py:75-76`: Extracts `is_in_doaj` and `is_core` from OpenAlex `primary_location.source`, labeling venues `"not in DOAJ or CORE"`, `"preprint"`, `"expression_of_concern"`, etc. | Surfaces an advisory warning to reviewers/students when an open-access journal is absent from both DOAJ and CWTS Leiden Core (`is_core`), without silently dropping valid regional works. |

---

### 3.2 Part 2: Faculty–Student Research Fit (`apps/documents/research_fit/` vs. `scilit/background/` & `discover/`)

| Dimension | `tehsil_agent` (`apps/documents/research_fit/papers.py`, `service.py`) | `scilit` (`src/scilit/background/{identify,profile,topics,run}.py`, `discover/{semantic,rerank}.py`) | Architectural Gap & Concrete Upgrade |
| :--- | :--- | :--- | :--- |
| **Faculty Identity Resolution** | `papers.py:87-114` (`person_matches_author`) + `L261-295` (`_query_openalex_works`): Searches OpenAlex works via `search.title_and_abstract=topic` (`per-page=15`) and checks if any authorship matches surname + first initial (`"M. Kaya"`). Optional `institution_id` filter. | `identify.py:52-174` (`resolve_identifier`, `_resolve_name`): Resolves a researcher to their canonical OpenAlex Author ID (`A...`) via ORCID (`https://api.openalex.org/authors/https://orcid.org/{orcid}`) or name + affiliation scoring before fetching their works (`filter=authorships.author.id:{aid}`). | Searching `works?search.title_and_abstract=topic&per-page=15` globally and filtering locally by surname + initial misses 99% of a professor's works when `topic` is broad (top 15 global papers in OpenAlex for "machine learning" will never contain that specific professor!). Filtering by `authorships.author.id` or `authorships.institutions.id` in OpenAlex fixes recall immediately. |
| **Topic Representation & Taxonomy** | Plain-text token bag (`_tokenize`, `len(w) >= 4` excluding `_STOPWORDS`, `papers.py:78-84`). No use of OpenAlex `primary_topic` or `topics` hierarchy. | `models.py:26-38` (`Topic`: `topic_id`, `name`, `subfield`, `field`, `domain`) + `profile.py:23-31` (`TopicCount`) + `run.py:75-122` (`build_background`): Uses OpenAlex's 4-level topic tree (`domain -> field -> subfield -> topic`) via `group_by=primary_topic.id` and `group_by=topics.id`. | Two works on `"Graph Neural Networks for Molecular Property Prediction"` and `"Equivariant Message Passing on 3D Conformers"` share OpenAlex `topic_id` / `subfield` even with zero 4-letter keyword overlap in the query string. |
| **Temporal / Career Trajectory Modeling** | `papers.py:40-41, 366-371`: Hard cutoff `_MAX_PAPER_AGE_YEARS = 6` and flat `+1` score if `year >= cutoff_year + 3`. No comparison against career topic baseline. | `topics.py:16, 39-85` (`RECENT_YEARS = 4`, `recency_shift`, `rank_candidates`) + `run.py:62-72` (`_emergent`): Computes `shift = recent_share - career_share` for every OpenAlex `primary_topic.id` (last 4 years vs. full career) and ranks adjacent emerging topics via co-occurrence facets. | Directly solves the "Topic Is Not Agenda" problem: prioritizes topics the professor is **actively pivoting into** (`recency_shift > 0`) and down-weights legacy topics the professor is **pivoting away from** (`recency_shift < -0.05`). |
| **Multi-Signal Retrieval & Reranking** | `papers.py:364-374`: Single linear score `overlap + (2 if role == "lead" else 0) + (1 if recent else 0)`. | `rerank.py:207-236` (`rrf_order`, Reciprocal Rank Fusion `1 / (k + rank)` with `RRF_K = 60`) + `semantic.py:81-107` (`openalex_semantic`). | Fusing lexical/topic overlap rank, OpenAlex `primary_topic` taxonomy rank, and recency/supervisory-role rank via RRF prevents a high-token-overlap middle-author paper from 5 years ago from outranking a recent last-author paper in the same OpenAlex topic. |
| **Byline Position & Supervisor vs. Student Role** | `papers.py:148-158` (`_author_role`): Collapses `"first"`, `"last"`, and `is_corresponding` into a single `"lead"` bucket. `discover_literature_person_on_page` (`L546-550`) accepts anyone on a page with `role == "lead"`. | Distinguishes first-author execution from senior/corresponding PI supervision and checks career `works_count` / multi-paper trajectory (`profile.py:41-53`). | Prevents `discover_literature_person_on_page` from mistaking a PhD student on a lab webpage (who has 1 first-author paper) for a faculty supervisor, and respects alphabetical-byline fields (mathematics, economics, theoretical CS). |

---

## 4. Verbatim-Verified Functions, Schemas, and Control Flows from `scilit` to Port into `tehsil_agent`

Per global engineering rules (*"when implementing a method or workflow from an existing tool or publication, copy its system prompts, inline user-prompt templates, schemas and control flow verbatim (verified against the source file) instead of paraphrasing or inventing your own"*), every code block below is copied **verbatim** from `/home/orkhan/code/scilit/src/scilit/` with exact file paths and line numbers, followed by how it wires into `tehsil_agent`.

---

### 4.1 Verbatim Component 1: Multi-Registry Citation, Chimeric, and Authorship Verification (`src/scilit/verify/citations.py`)

#### Source File: `/home/orkhan/code/scilit/src/scilit/verify/citations.py`
- **Lines 43–88**: `CitationCheck` dataclass, `title_matches` (combining `rapidfuzz.fuzz.token_sort_ratio >= 90` with unbroken 4-token subtitle containment), and `_surname` (NFKD diacritic stripping + particle removal).
- **Lines 90–199**: `_Registry` normalized record and the three CC0 registry adapters (`_crossref_registry`, `_openalex`, `_arxiv`).
- **Lines 202–351**: `_judge` (deterministic agreement scoring across title, first/all author surnames, year, retraction, and `chimeric` flagging), `_check_one` (cascading Crossref + OpenAlex + arXiv + DOI Handle API lookup), and `_handle` (`https://doi.org/api/handles/{doi}`).
- **Lines 916–981**: `_search_title_in_registries` (Tier-2 title-search fallback across OpenAlex and Crossref when a publication has no DOI or its DOI fails).

```python
# VERBATIM FROM /home/orkhan/code/scilit/src/scilit/verify/citations.py:34-88
CROSSREF = "https://api.crossref.org/works/"
OPENALEX = "https://api.openalex.org/works/"
HANDLE = "https://doi.org/api/handles/"
ARXIV = "http://export.arxiv.org/api/query"
ATOM = "{http://www.w3.org/2005/Atom}"
ARXIV_DOI_PREFIX = "10.48550/arxiv."
TITLE_SIMILARITY_FLOOR = 90
MIN_SUBTITLE_TOKENS = 4


@dataclass
class CitationCheck:
    doi: str
    claimed_title: str
    claimed_first_author: str = ""
    claimed_year: int | None = None
    status: str = "unverified"
    resolved_title: str | None = None
    resolved_first_author: str | None = None
    resolved_year: int | None = None
    retracted: bool = False
    preprint: bool = False
    chimeric: bool = False
    author_overlap: float | None = None
    sources: list[str] = field(default_factory=list)


def title_matches(a: str, b: str) -> bool:
    """Fuzzy token-sort match, or a colon-subtitle suffix that appears as an
    unbroken word run in the longer title (books indexed as 'Series: Subtitle')."""
    if not a or not b:
        return False
    if fuzz.token_sort_ratio(a, b) >= TITLE_SIMILARITY_FLOOR:
        return True
    toks_a = re.findall(r"[a-z0-9]+", a.lower())
    toks_b = re.findall(r"[a-z0-9]+", b.lower())
    short, long = (toks_a, toks_b) if len(toks_a) <= len(toks_b) else (toks_b, toks_a)
    if len(short) < MIN_SUBTITLE_TOKENS or len(short) == len(long):
        return False
    span = len(short)
    return any(long[i : i + span] == short for i in range(len(long) - span + 1))


def _surname(name: str) -> str:
    if not name:
        return ""
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    s = s.strip()
    if "," in s:
        s = s.split(",", 1)[0]
    else:
        parts = [p for p in re.split(r"[\s.]+", s) if len(p) > 1]
        s = parts[-1] if parts else s
    return re.sub(r"[^a-z]", "", s.lower())
```

```python
# VERBATIM FROM /home/orkhan/code/scilit/src/scilit/verify/citations.py:90-273
@dataclass
class _Registry:
    source: str
    title: str | None
    first_surname: str
    all_surnames: set[str]
    year: int | None
    retracted: bool = False
    preprint: bool = False


def _crossref_registry(msg: dict[str, Any]) -> _Registry:
    titles = msg.get("title") or []
    title = titles[0] if titles else None
    authors = msg.get("author") or []
    surnames = {_surname(a.get("family") or a.get("name") or "") for a in authors}
    surnames.discard("")
    first = _surname(authors[0].get("family") or authors[0].get("name") or "") if authors else ""
    year = None
    for key in ("published-print", "published-online", "issued", "created"):
        parts = (msg.get(key) or {}).get("date-parts") or []
        if parts and parts[0]:
            year = parts[0][0]
            break
    updates = list(msg.get("update-to") or []) + list(msg.get("updated-by") or [])
    retracted = any(
        "retract" in (u.get("type") or "").lower() or "withdraw" in (u.get("type") or "").lower()
        for u in updates
    )
    kind = (msg.get("type") or "").lower()
    return _Registry(
        source="crossref",
        title=title,
        first_surname=first,
        all_surnames=surnames,
        year=year,
        retracted=retracted,
        preprint=kind == "posted-content",
    )


def _openalex(client: httpx.Client, doi: str) -> _Registry | None:
    try:
        r = client.get(f"{OPENALEX}https://doi.org/{doi}")
    except httpx.HTTPError as e:
        log.warning("openalex citation lookup failed for %s: %s", doi, e)
        return None
    if r.status_code != 200:
        return None
    msg = r.json()
    title = msg.get("title") or msg.get("display_name")
    authorships = msg.get("authorships") or []
    surnames: set[str] = set()
    first = ""
    for i, a in enumerate(authorships):
        dn = (a.get("author") or {}).get("display_name") or a.get("raw_author_name") or ""
        sn = _surname(dn)
        if sn:
            surnames.add(sn)
            if i == 0:
                first = sn
    year = msg.get("publication_year")
    loc = msg.get("primary_location") or {}
    src = (loc.get("source") or {}).get("type") or ""
    kind = (msg.get("type") or "").lower()
    return _Registry(
        source="openalex",
        title=title,
        first_surname=first,
        all_surnames=surnames,
        year=year,
        retracted=bool(msg.get("is_retracted")),
        preprint=kind == "preprint" or src == "repository",
    )


def _arxiv(client: httpx.Client, arxiv_id: str) -> _Registry | None:
    try:
        r = client.get(ARXIV, params={"id_list": arxiv_id})
    except httpx.HTTPError as e:
        log.warning("arxiv citation lookup failed for %s: %s", arxiv_id, e)
        return None
    if r.status_code != 200:
        return None
    root = ET.fromstring(r.text)
    entry = root.find(f"{ATOM}entry")
    if entry is None or entry.findtext(f"{ATOM}id") is None:
        return None
    title = (entry.findtext(f"{ATOM}title") or "").strip() or None
    if not title or title.lower() == "error":
        return None
    authors = [
        (a.findtext(f"{ATOM}name") or "").strip() for a in entry.findall(f"{ATOM}author")
    ]
    surnames = {_surname(n) for n in authors if _surname(n)}
    first = _surname(authors[0]) if authors else ""
    pub = entry.findtext(f"{ATOM}published") or ""
    year = int(pub[:4]) if len(pub) >= 4 and pub[:4].isdigit() else None
    return _Registry(
        source="arxiv",
        title=title,
        first_surname=first,
        all_surnames=surnames,
        year=year,
        preprint=True,
    )


def _judge(
    doi: str,
    claimed_title: str,
    claimed_first_author: str,
    claimed_year: int | None,
    regs: list[_Registry],
    claimed_authors: list[str] | None = None,
) -> CitationCheck:
    retracted = any(r.retracted for r in regs)
    preprint = all(r.preprint for r in regs)
    sources = [r.source for r in regs]
    primary = regs[0]

    title_ok = any(r.title and title_matches(claimed_title, r.title) for r in regs)
    if not any(r.title for r in regs):
        status = "unverified"
    elif not claimed_title or title_ok:
        status = "retracted" if retracted else "verified"
    else:
        status = "title_mismatch"

    claimed_sn = _surname(claimed_first_author)
    author_ok = True
    overlap: float | None = None
    reg_all_surnames: set[str] = set()
    for r in regs:
        reg_all_surnames.update(r.all_surnames)

    if claimed_authors:
        c_surnames = {_surname(a) for a in claimed_authors if _surname(a)}
        if c_surnames and reg_all_surnames:
            overlap = len(c_surnames & reg_all_surnames) / len(c_surnames)
            if overlap == 0.0:
                author_ok = False
    elif claimed_sn and any(r.all_surnames for r in regs):
        author_ok = any(
            claimed_sn == r.first_surname or claimed_sn in r.all_surnames for r in regs
        )
        overlap = 1.0 if author_ok else 0.0

    year_ok = True
    if claimed_year and any(r.year for r in regs):
        year_ok = any(r.year and abs(claimed_year - r.year) <= 1 for r in regs)

    chimeric = status == "title_mismatch" or (
        status == "verified" and (not author_ok or not year_ok)
    )
    if chimeric and status == "verified":
        status = "chimeric"

    return CitationCheck(
        doi=doi,
        claimed_title=claimed_title,
        claimed_first_author=claimed_first_author,
        claimed_year=claimed_year,
        status=status,
        resolved_title=primary.title,
        resolved_first_author=primary.first_surname or None,
        resolved_year=primary.year,
        retracted=retracted,
        preprint=preprint,
        chimeric=chimeric,
        author_overlap=overlap,
        sources=sources,
    )
```

```python
# VERBATIM FROM /home/orkhan/code/scilit/src/scilit/verify/citations.py:276-351, 916-981
def _check_one(
    client: httpx.Client,
    doi: str,
    title: str,
    first_author: str = "",
    year: int | None = None,
    authors: list[str] | None = None,
) -> CitationCheck:
    clean = doi.strip().removeprefix("https://doi.org/").removeprefix("http://doi.org/")
    regs: list[_Registry] = []
    if clean.lower().startswith(ARXIV_DOI_PREFIX):
        aid = clean[len(ARXIV_DOI_PREFIX) :]
        ar = _arxiv(client, aid)
        if ar:
            regs.append(ar)
    else:
        cr_msg = fetch_crossref_work(clean, client=client)
        if cr_msg is not None:
            regs.append(_crossref_registry(cr_msg))
    oa = _openalex(client, clean)
    if oa:
        regs.append(oa)
    if regs:
        return _judge(clean, title, first_author, year, regs, claimed_authors=authors)
    h = _handle(client, clean, title, first_author, year)
    if h is not None:
        return h
    return CitationCheck(
        doi=clean,
        claimed_title=title,
        claimed_first_author=first_author,
        claimed_year=year,
        status="not_found",
    )


def _handle(
    client: httpx.Client,
    doi: str,
    title: str,
    first_author: str,
    year: int | None,
) -> CitationCheck | None:
    """Last-chance check via the DOI Handle system ( catches DataCite / mEDRA
    DOIs that Crossref and OpenAlex do not index )."""
    try:
        r = client.get(f"{HANDLE}{doi}")
    except httpx.HTTPError as e:
        log.warning("doi handle lookup failed for %s: %s", doi, e)
        return None
    if r.status_code == 200 and r.json().get("responseCode") == 1:
        return CitationCheck(
            doi=doi,
            claimed_title=title,
            claimed_first_author=first_author,
            claimed_year=year,
            status="handle_only",
            sources=["handle"],
        )
    if r.status_code == 404 or r.json().get("responseCode") == 100:
        return CitationCheck(
            doi=doi,
            claimed_title=title,
            claimed_first_author=first_author,
            claimed_year=year,
            status="not_found",
            sources=["handle"],
        )
    return None


def _search_title_in_registries(
    client: httpx.Client,
    title: str,
    first_author: str = "",
    year: int | None = None,
) -> list[_Registry]:
    """Tier 2 fallback: Search OpenAlex and Crossref by title when DOI is missing or invalid."""
    if not title or len(title.strip()) < 8:
        return []
    regs: list[_Registry] = []
    # 1. Try OpenAlex search
    try:
        r = client.get(OPENALEX[:-1], params={"search": title, "per-page": 5})
        if r.status_code == 200:
            results = r.json().get("results") or []
            for msg in results:
                cand_title = msg.get("title") or msg.get("display_name") or ""
                if title_matches(title, cand_title):
                    authorships = msg.get("authorships") or []
                    surnames: set[str] = set()
                    first = ""
                    for i, a in enumerate(authorships):
                        dn = (a.get("author") or {}).get("display_name") or a.get("raw_author_name") or ""
                        sn = _surname(dn)
                        if sn:
                            surnames.add(sn)
                            if i == 0:
                                first = sn
                    pub_year = msg.get("publication_year")
                    loc = msg.get("primary_location") or {}
                    src = (loc.get("source") or {}).get("type") or ""
                    kind = (msg.get("type") or "").lower()
                    regs.append(
                        _Registry(
                            source="openalex_search",
                            title=cand_title,
                            first_surname=first,
                            all_surnames=surnames,
                            year=pub_year,
                            retracted=bool(msg.get("is_retracted")),
                            preprint=kind == "preprint" or src == "repository",
                        )
                    )
                    break
    except httpx.HTTPError as e:
        log.warning("openalex title search failed for '%s': %s", title, e)

    # 2. Try Crossref search if OpenAlex didn't find a strong match
    if not regs:
        try:
            r = client.get(CROSSREF[:-1], params={"query.bibliographic": title, "rows": 3})
            if r.status_code == 200:
                items = (r.json().get("message") or {}).get("items") or []
                for msg in items:
                    titles = msg.get("title") or []
                    cand_title = titles[0] if titles else ""
                    if title_matches(title, cand_title):
                        reg = _crossref_registry(msg)
                        reg.source = "crossref_search"
                        regs.append(reg)
                        break
        except httpx.HTTPError as e:
            log.warning("crossref title search failed for '%s': %s", title, e)

    return regs
```

---

### 4.2 Verbatim Component 2: Retraction, Expression of Concern, Preprint-to-Published Linking & DOAJ/CORE Venue Quality (`src/scilit/acquire/hygiene.py`)

#### Source File: `/home/orkhan/code/scilit/src/scilit/acquire/hygiene.py`
- **Lines 16–75**: `RETRACTION_TYPES`, `NOTE_TYPES`, `CrossrefFacts`, `crossref_facts()`, and `_linked_id()`.
- **Lines 173–200**: `source_labels()` (attaches `"preprint"`, `"expression_of_concern"`, `"not in DOAJ or CORE"` labels to a record).

```python
# VERBATIM FROM /home/orkhan/code/scilit/src/scilit/acquire/hygiene.py:16-75, 173-200
RETRACTION_TYPES = frozenset(
    {"retraction", "partial_retraction", "withdrawal", "removal"}
)
NOTE_TYPES = frozenset(
    {"expression_of_concern", "correction", "corrigendum", "erratum", "addendum"}
)


@dataclass
class CrossrefFacts:
    retracted: bool = False
    update_notes: list[str] = field(default_factory=list)
    preprint_of: str | None = None
    has_preprint: str | None = None
    kind: str | None = None


def crossref_facts(doi: str, client: httpx.Client | None = None) -> CrossrefFacts:
    msg = fetch_crossref_work(doi, client=client)
    if msg is None:
        return CrossrefFacts()
    facts = CrossrefFacts(kind=(msg.get("type") or "").lower() or None)
    for key in ("update-to", "updated-by"):
        for u in msg.get(key) or []:
            utype = (u.get("type") or "").lower().replace("-", "_").replace(" ", "_")
            if utype in RETRACTION_TYPES:
                facts.retracted = True
            elif utype in NOTE_TYPES and utype not in facts.update_notes:
                facts.update_notes.append(utype)
    rel = msg.get("relation") or {}
    for item in rel.get("is-preprint-of") or []:
        target = _linked_id(item)
        if target:
            facts.preprint_of = target
            break
    for item in rel.get("has-preprint") or []:
        target = _linked_id(item)
        if target:
            facts.has_preprint = target
            break
    return facts


def _linked_id(item: dict[str, Any]) -> str | None:
    if (item.get("id-type") or "").lower() != "doi":
        return None
    raw = (item.get("id") or "").strip()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if raw.lower().startswith(prefix):
            raw = raw[len(prefix) :]
    return raw.lower() or None


def source_labels(p: PaperRecord) -> list[str]:
    """Venue and version hygiene tags shown on the evidence table. Informative,
    never a filter: the judge or user decides what to make of them."""
    labels: list[str] = []
    if p.is_preprint or (
        p.doi and p.doi.lower().startswith(("10.1101/", "10.21203/", "10.26434/"))
    ):
        if not p.version_of:
            labels.append("preprint")
    if p.version_of:
        labels.append(f"published (merged preprint {p.has_preprint or ''})".strip())
    for note in p.update_notes:
        labels.append(note)
    if p.in_doaj is False and p.is_core is False and not p.is_preprint and p.journal:
        labels.append("not in DOAJ or CORE")
    return labels
```

---

### 4.3 Verbatim Component 3: Researcher Identity Resolution, OpenAlex Topic Hierarchy & Recency-Shift Agenda Modeling (`src/scilit/background/`)

#### Source Files:
- `/home/orkhan/code/scilit/src/scilit/background/identify.py` (lines 18–59, 147–174)
- `/home/orkhan/code/scilit/src/scilit/background/profile.py` (lines 23–53, 102–133)
- `/home/orkhan/code/scilit/src/scilit/background/topics.py` (lines 16–85)
- `/home/orkhan/code/scilit/src/scilit/background/run.py` (lines 62–122)

```python
# VERBATIM FROM /home/orkhan/code/scilit/src/scilit/background/identify.py:18-59, 147-174
OPENALEX = "https://api.openalex.org"
ORCID_RE = re.compile(r"(?:https?://orcid\.org/)?(\d{4}-\d{4}-\d{4}-\d{3}[\dX])", re.I)
OA_AUTHOR_RE = re.compile(r"(?:https?://openalex\.org/)?([Aa]\d{4,})")


class AmbiguousResearcherError(ValueError):
    def __init__(self, query: str, candidates: list[AuthorIdentity]) -> None:
        self.query = query
        self.candidates = candidates
        lines = [f"Multiple OpenAlex authors match {query!r}; re-run with an OpenAlex ID or ORCID:"]
        for c in candidates:
            inst = f" ({c.institution})" if c.institution else ""
            orcid = f" orcid={c.orcid}" if c.orcid else ""
            lines.append(
                f"  {c.openalex_id}  {c.display_name}{inst}  "
                f"works={c.works_count} cited_by={c.cited_by_count}{orcid}"
            )
        super().__init__("\n".join(lines))


def classify_identifier(raw: str) -> tuple[str, str]:
    s = raw.strip()
    m = ORCID_RE.fullmatch(s)
    if m:
        return "orcid", m.group(1).upper()
    m = OA_AUTHOR_RE.fullmatch(s)
    if m:
        return "openalex", "A" + m.group(1)[1:]
    return "name", s


def resolve_identifier(
    raw: str,
    *,
    affiliation: str | None = None,
    allow_ambiguous: bool = False,
    client: httpx.Client | None = None,
) -> AuthorIdentity:
    kind, value = classify_identifier(raw)
    own = client is None
    c = client or http_client()
    try:
        if kind == "openalex":
            r = c.get(f"{OPENALEX}/authors/{value}", params=oa_params())
            r.raise_for_status()
            return _parse_author(r.json())
        if kind == "orcid":
            r = c.get(
                f"{OPENALEX}/authors/https://orcid.org/{value}",
                params=oa_params(),
            )
            r.raise_for_status()
            return _parse_author(r.json())
        return _resolve_name(
            c, value, affiliation=affiliation, allow_ambiguous=allow_ambiguous
        )
    finally:
        if own:
            c.close()
```

```python
# VERBATIM FROM /home/orkhan/code/scilit/src/scilit/background/topics.py:16-85
RECENT_YEARS = 4


@dataclass(frozen=True)
class TopicSuggestion:
    topic_id: str
    display_name: str
    relationship: str  # "core" | "recent_shift" | "adjacent"
    career_count: int = 0
    recent_count: int = 0
    co_occurrence: int = 0
    shift: float = 0.0
    subfield: str | None = None
    field: str | None = None
    domain: str | None = None


def recency_shift(
    career: list[TopicCount], recent: list[TopicCount]
) -> dict[str, tuple[int, int, float]]:
    """Map topic_id -> (career_count, recent_count, recent_share - career_share)."""
    c_total = sum(t.count for t in career) or 1
    r_total = sum(t.count for t in recent) or 1
    c_map = {t.topic_id: t.count for t in career}
    r_map = {t.topic_id: t.count for t in recent}
    out: dict[str, tuple[int, int, float]] = {}
    for tid in set(c_map) | set(r_map):
        cc = c_map.get(tid, 0)
        rc = r_map.get(tid, 0)
        out[tid] = (cc, rc, (rc / r_total) - (cc / c_total))
    return out


def rank_candidates(
    career_primary: list[TopicCount],
    recent_primary: list[TopicCount],
    co_occurring: list[TopicCount],
    *,
    limit: int = 10,
) -> list[TopicSuggestion]:
    shifts = recency_shift(career_primary, recent_primary)
    names = {t.topic_id: t.display_name for t in (*career_primary, *recent_primary, *co_occurring)}
    core_ids = {t.topic_id for t in career_primary[:5]}

    suggestions: list[TopicSuggestion] = []
    for t in career_primary[:5]:
        cc, rc, sh = shifts.get(t.topic_id, (t.count, 0, 0.0))
        suggestions.append(
            TopicSuggestion(
                topic_id=t.topic_id,
                display_name=t.display_name,
                relationship="core",
                career_count=cc,
                recent_count=rc,
                shift=round(sh, 3),
            )
        )

    rising = sorted(
        (tid for tid in shifts if tid not in core_ids and shifts[tid][1] >= 2),
        key=lambda tid: (shifts[tid][2], shifts[tid][1]),
        reverse=True,
    )
    for tid in rising[:5]:
        cc, rc, sh = shifts[tid]
        if sh <= 0:
            continue
        suggestions.append(
            TopicSuggestion(
                topic_id=tid,
                display_name=names.get(tid, tid),
                relationship="recent_shift",
                career_count=cc,
                recent_count=rc,
                shift=round(sh, 3),
            )
        )

    seen = {s.topic_id for s in suggestions}
    for t in co_occurring:
        if t.topic_id in seen:
            continue
        cc, rc, sh = shifts.get(t.topic_id, (0, 0, 0.0))
        suggestions.append(
            TopicSuggestion(
                topic_id=t.topic_id,
                display_name=t.display_name,
                relationship="adjacent",
                career_count=cc,
                recent_count=rc,
                co_occurrence=t.count,
                shift=round(sh, 3),
            )
        )
        if len(suggestions) >= limit + 5:
            break

    return suggestions[:limit]
```

```python
# VERBATIM FROM /home/orkhan/code/scilit/src/scilit/discover/rerank.py:22-23, 207-236
RRF_K = 60


def rrf_order(
    question: str,
    papers: list[PaperRecord],
    *,
    top_n: int | None = None,
) -> list[PaperRecord]:
    """Reciprocal Rank Fusion over the existing channel order and BM25 lexical
    rank (`1 / (k + rank)`), with an abstract bonus so metadata-only stubs lose
    ties. Used when the cross-encoder is unavailable or disabled."""
    if not papers:
        return []
    bm = bm25_order(question, papers)
    bm_rank = {id(p): i for i, p in enumerate(bm)}
    q_toks = set(_tok(question))

    def score(idx_p: tuple[int, PaperRecord]) -> tuple[float, int, int]:
        ch_i, p = idx_p
        rrf = 1.0 / (RRF_K + ch_i) + 1.0 / (RRF_K + bm_rank[id(p)])
        p_toks = set(_tok(f"{p.title} {p.abstract or ''}"))
        overlap = len(q_toks & p_toks)
        return (rrf, 1 if p.abstract else 0, overlap)

    ranked = [p for _, p in sorted(enumerate(papers), key=score, reverse=True)]
    for p in ranked:
        if p.rerank_score is None:
            p.rerank_score = 1.0 / (RRF_K + bm_rank[id(p)])
    return ranked[:top_n] if top_n else ranked
```

---

## 5. Concrete Porting Blueprint for `tehsil_agent`

### 5.1 Blueprint A: Upgrading `apps/documents/evidence/publication.py`, `facts.py`, and `ingestion.py`

1. **Extend `PublicationFacts` in `apps/documents/evidence/publication.py:29-36`**:
   - Add hygiene and verification fields populated from Crossref + OpenAlex + arXiv:
     ```python
     @dataclass(frozen=True)
     class PublicationFacts:
         doi: str
         title: str
         authors: list[str]
         venue: str | None
         year: int | None
         work_type: str | None
         abstract: str | None
         is_retracted: bool = False
         update_notes: tuple[str, ...] = ()
         is_preprint: bool = False
         preprint_of_doi: str | None = None
         in_doaj: bool | None = None
         is_core: bool | None = None
     ```
2. **Add Preprint-to-Published Upgrade & Retraction Gate in `apps/documents/evidence/publication.py` and `facts.py`**:
   - In `_from_crossref()` (`publication.py:49-70`), parse `update-to`, `updated-by`, and `relation.is-preprint-of` using `scilit/src/scilit/acquire/hygiene.py::crossref_facts` (`L33-59`).
   - If `facts.preprint_of` is present (e.g., a student gives a `10.1101/...` bioRxiv DOI that has since been published in a journal), automatically follow `facts.preprint_of` to fetch the peer-reviewed journal record!
   - In `_from_openalex()` (`publication.py:73-95`), extract `bool(msg.get("is_retracted"))`, `source.get("is_in_doaj")`, and `source.get("is_core")`.
   - In `publication_entry()` (`apps/documents/evidence/facts.py:66-81`), raise `UnusablePublication(f"DOI {pub.doi} has been retracted")` if `pub.is_retracted` is `True`. If `pub.is_preprint` is `True` (and not yet merged into a published journal article via `preprint_of_doi`), map `status` to `PublicationStatus.UNDER_REVIEW` (or a dedicated preprint status) rather than crashing with `UnusablePublication`.
3. **Add `verify_claimed_publication()` to `apps/documents/evidence/publication.py` and Call It in `ingest_uploaded_cv()` (`apps/documents/ingestion.py:454-466`)**:
   - Port `title_matches`, `_surname`, `_judge`, `_check_one`, `_handle`, and `_search_title_in_registries` from `scilit/src/scilit/verify/citations.py`.
   - When `ingest_uploaded_cv()` extracts a `PublicationEntry` from an uploaded CV:
     - Run `_check_one()` (if `pub.doi` is present) or `_search_title_in_registries()` (if `pub.doi` is absent and `pub.status == PublicationStatus.PUBLISHED`).
     - Verify that at least one surname in `known_owner_names(student)` (normalized via `_surname()` with `NFKD` diacritic stripping) appears in `reg_all_surnames`.
     - If `check.status == "verified"` and the student is a verified author: upgrade the ledger fact (`VerifiedFact`) with the canonical DOI/venue/authors and `source_tier=SourceTier.AUTHORITATIVE_DOCUMENT`.
     - If `check.status in {"chimeric", "title_mismatch", "retracted", "not_found"}` or the student's surname is absent from `reg_all_surnames`: attach a structured verification warning on the `VerifiedFact` / `GapQuestion` so the student must resolve or remove the unverified publication before it can enter a generated CV or letter.

### 5.2 Blueprint B: Upgrading `apps/documents/research_fit/papers.py` and `service.py`

1. **Two-Step Faculty Disambiguation (`apps/documents/research_fit/papers.py`)**:
   - Before querying `works?search.title_and_abstract=topic&per-page=15` globally, resolve the candidate professor's OpenAlex Author ID (`A...`) using `_resolve_name` from `scilit/src/scilit/background/identify.py` scoped by `affiliations.institution.id:{institution_id}` (or `last_known_institutions.id:{institution_id}`).
   - Then query OpenAlex works filtered by `authorships.author.id:{author_id}` (or `authorships.institutions.id:{institution_id}` when author ID is ambiguous). This eliminates the 15-result global top-page bottleneck where a faculty member's papers were omitted whenever global works on `topic` exceeded 15.
2. **Incorporate OpenAlex `primary_topic` Hierarchy + `recency_shift` (`apps/documents/research_fit/papers.py:310-379`)**:
   - Request `primary_topic,topics` in OpenAlex `select` fields (`_OPENALEX_WORKS_URL`).
   - Port `recency_shift()` from `scilit/src/scilit/background/topics.py:39-50` over the professor's works (`RECENT_YEARS = 4` vs. career).
   - Fuse three signals via `rrf_order` (`scilit/src/scilit/discover/rerank.py:207-236`):
     1. Lexical/keyphrase overlap (`_topic_overlap_score`),
     2. OpenAlex `primary_topic` / `subfield` match against the student's confirmed `PUBLICATION` / `PROJECT` / `THESIS` facts and programme topics, and
     3. Positive topic drift (`shift >= 0` in `recency_shift`, penalizing legacy topics with `shift < -0.05`).
3. **Separate Supervisory Role (`pi_supervisor`) from Trainee First-Author Role (`apps/documents/research_fit/papers.py:148-158, 546-550`)**:
   - Split `_author_role()` into `"senior_lead"` (`author_position == "last" or is_corresponding`), `"first_lead"` (`author_position == "first"`), and `"group"` (`author_position == "middle"`).
   - In `discover_literature_person_on_page()` (`papers.py:514-565`), require either `"senior_lead"` authorship or `works_count >= 5` on the resolved OpenAlex author profile before proposing a person on a department page as a prospective faculty supervisor.
