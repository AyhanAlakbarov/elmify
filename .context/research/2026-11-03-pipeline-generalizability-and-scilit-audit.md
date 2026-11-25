# End-to-End 8-Stage Pipeline Generalizability & `scilit` Research Audit

**Date:** 2026-11-03
**Scope:** All 8 pipeline stages of `tehsil_agent` (`apps/accounts/`, `apps/concierge/`, `apps/reference_data.py`, `apps/research/`, `apps/funding/`, `apps/documents/`, `apps/portals/`, `apps/mailbox/`, `apps/dashboard/`, `extension/`).
**Totals:** **149 line-cited hardcoded / non-generalizable findings** and **10 consolidated high-ROI `scilit` deep-research & direct code-port targets**.

---

## Executive Summary of Cross-Cutting Blind Spots

Across all 8 stages, the remaining hardcodings cluster into 7 root causes:
1. **Narrow Country, Currency & Region Tables:** `COUNTRY_TO_CURRENCY` maps only 7 countries; `COMMON_CURRENCIES` in the browser `<select>` renders only 15 currencies (turning `CAD`/`JPY`/`NGN` into `EUR`); `vocabulary.py` only ships `resolver_data/{CC}.json` for 8 countries; `REGIONS` omits `MERCOSUR`, `GCC`, `ASEAN`/`SAARC`, `ECOWAS`, `NORDIC`, `BENELUX`, `EFTA`; and `extension/src/content/fill.ts` only has `<select>` country synonyms for 5 countries and no `F`/`M` gender synonyms.
2. **4-to-6 Language Regex Ceilings & Script Stripping:** Transcript PII scrubbing (`transcript.py`), translation-page filtering (`transcript_pages.py`), extension form verification (`vocabulary.ts` + `verify.ts`), portal password rules (`credentials.py`), and `vouch.py` only recognize 4–6 languages and strip non-Latin scripts (`[^a-z0-9]`), causing Dutch/Italian/Polish/Spanish/CJK portal autofill to be rejected at runtime, non-English original pages in translation PDFs to double-count courses, and non-EN/TR/AZ/RU student PII to leak to LLMs.
3. **Aggressive Substring PII Redaction & Course-Code Masking Bugs:**
   - `referee_package.py:454` masks any 3+ letter name substring without word boundaries (`"Ali"` -> `"an[CANDIDATE_NAME]tical"`, `"qu[CANDIDATE_NAME]fied"`).
   - `decision_reader.py:76` redacts any email word matching a folded student name token (`"Can"` -> `"You [name] view your offer"`).
   - `transcript.py:67,359,392` drops entire university header lines containing 6-digit postal codes and masks 6-digit course catalog codes (`5710111`) to `#`.
   - `letter_gates.py:117` treats every 2-word capitalized phrase as an undeclared proper noun, breaking German (`de`) letters where all nouns are capitalized.
4. **International Grading Scale & Multi-Test Language Contradictions:**
   - Linear Bavarian interpolation penalizes grade-deflated systems (French `14/20` *Mention Bien* -> `2.8` GPA), fails on inverted scales (Czech/Slovak `1–4`, Philippine `1–5`, German `1.0–5.0` in `transcript_checks.py`), and collides `"First Class"` between UK (`>=70%`, `1.5` Bavarian) and India (`>=60%`, `2.5` Bavarian).
   - `eligibility.py` has an internal contradiction between `_to_ielts_equiv` (`PTE 65 / Duolingo 125 -> C1`) and `_level_to_cefr` (`PTE 70 / Duolingo 125 -> B2`), and rejects numeric scores for 25+ non-English exams (`TestDaF`, `Goethe`, `DELF/DALF`, `TCF`, `DELE`, `CILS`, `HSK`, `JLPT`, `TOPIK`, `TÖMER`).
5. **Northern-Hemisphere / Master's-Only / 2-Semester-Only Calendar & Tuition Assumptions:**
   - `programme_scraper/extractors.py`, `validity.py`, `angles.py`, and `cycle_verification.py` assume a single Northern-Hemisphere September intake (`d.month >= 9` shifts Southern-Hemisphere/October deadlines back 1 year; Wayback probes in July/August cache off-season `"closed"` banners as definitive).
   - Tier-1 tuition arbitration omits `"PER_CREDIT"` from `ProgrammeQuestionSet`, recording **1 single credit hour's fee as full annual tuition**, and `funding_judge.py` erases `"SEMESTER"` scholarship amounts as uncountable `"OTHER"`.
6. **Greedy 1D Pack Portfolio Selection & Correlated Funder Risk:**
   - `pack.py` uses a greedy 1D traversal that fails on fee-budget knapsack tradeoffs, rewards low personal admission chance (`(50 - eff_chance) * 0.15`) under `top_only`, deducts `fee_in_base` without `BANK_MARGIN`, and ignores correlated failure when multiple programmes rely on the same external scholarship (`DAAD`, `Chevening`, `DP`).
7. **Cross-Cultural Personal Name & Legal-Entity Matching:**
   - East Asian / Hungarian surname-first order without commas (`"Zhang Wei"`), Hispanic double surnames, second-given-name usage (`"Marie Jean Dupont"` -> `"Jean Dupont"`), mononyms (`"Sukarno"`), and CJK legal-entity wrappers (`"国立大学法人東京大学"`) fail in `id_reading.py`, `publication.py`, `research_fit/papers.py`, `prepare.py`, and `recognition.py`.

---

## Stage-by-Stage Findings Summary

### Stage 1: Student Intake, Profile & Field Taxonomy (`apps/accounts/`, `apps/concierge/`, `apps/reference_data.py`) — 19 Findings
1. `question_widgets.py:24-40,165-171` & `forms.py:300-303`: Browser currency `<select>` only renders 15 `COMMON_CURRENCIES` (out of 179 `ISO_4217_CODES`), silently resetting `CAD`, `JPY`, `CHF`, `PLN`, `NGN`, `BRL` to `EUR`.
2. `reference_data.py:38-46` & `consultation.py:941-1028`: `COUNTRY_TO_CURRENCY` has only 7 countries and `_COUNTRY_CURRENCY_HINTS` falls back to `"EUR"` for ~160 territories instead of reading `babel.numbers.get_territory_currencies`.
3. `forms.py:51-121` & `question_widgets.py:63-88`: Duplicate English-only country resolvers + `.upper()` (breaking Turkish dotted `İ` in `"İtalya"` and native endonyms like `"Österreich"`, `"Schweiz"`, `"España"`, `"Polska"`).
4. `views.py:72,127-155`: `_ANGLOPHONE_CODES` omits `MT, SG, BB, JM, TT, GY, BZ` and warns about `IELTS/TOEFL` even when `acceptable_teaching_languages` is `["German"]` or `["Turkish"]`.
5. `forms.py:359,394,553-558,814`: `_LANGUAGE_ROWS = 3` silently deletes 4th+ verified languages on edit, and blank `DEGREE` evidence fabricates `"C1"`.
6. `forms.py:452-498` & `consultation.py:214-222,923`: Single-degree UI drops 2nd degree on prefill, and editing the university name string (`"Baku State Uni"` -> `"Baku State University"`) wipes all extracted transcript `courses` (`[]`).
7. `consultation.py:744,778-780,823-825`: `len(raw_date) == 10` date slicing drops `YYYY-MM` graduation dates and crashes on `DD.MM.YYYY` certificate dates.
8. `forms.py:260-281` & `views.py:82-85`: `presets[2][0]` seeds `intended_intake` to Spring of next year (`2028-02-01`) when onboarding in January.
9. `consultation.py:379-655`: `_NO_FUNDING_NEEDED_RE` has optional `(?:needed|...)?`, so `"I have no funding from my family, I need a scholarship"` overwrites `funding_dependency = "MANDATORY"` to `"OPTIONAL"`! Also `"1.5 years"` parses as `5 years` (`60 months`).
10. `schemas.py:186` & `forms.py:194-208`: Binary `ONE_YEAR` / `TWO_YEAR` duration enum cannot represent 1.5-year (90 ECTS) Master's programmes.
11. `schemas.py:129-139`: Static `DEFAULT_WEIGHTS` ignores `career_intent` (`PHD` still gets `RESEARCH_FIT = 0.10`) and `funding_dependency`.
12. `profile_versions.py:88-100`: Strict `.casefold()` equality on `qualification` and `field` raises false-positive `identity_mismatch` alert when expanding `"BSc CS"` to `"Bachelor of Science in Computer Science"`.
13. `field_taxonomy.py:188,192-194`: `len(tok) < 3` drops all 2-char CJK discipline nouns (`化学`, `物理`, `法学`) and 2-letter acronyms (`SE`, `EE`, `ME`, `CE`, `OR`, `DS`).
14. `field_taxonomy.py:4143-4168`: `_decompose_morphological_compound` aborts on multi-word inputs (`if len(words) > 1: return None`, failing `"Applied Geoinformatics"`) and non-ASCII characters (`r"[a-z]+"`).
15. `field_taxonomy.py:4760-4809,5185-5199`: Broad umbrella majors (`"Computer Science"`, `"Chemistry"`) have `is_ambiguous_or_interdisciplinary = False` and skip the `research_interests` question.
16. `field_taxonomy.py:224-253,4232-4349`: `_METHOD_TERMS` lumps `"sustainable"` and `"quantum"` with `"ai"`, turning `"Sustainable Agriculture"` into `"AI, Digital & Computational Agriculture"`.
17. `field_taxonomy.py:4554-4589,4673-4684`: `_drop_named_run` deletes the entire capitalized string `"Technische Universität München Informatik"` because `"Universität"` is in the run.
18. `field_taxonomy.py:5591-5672,5732-5735`: Feminine-only adjective templates (`"droit appliquée"`, `"прикладная право"`) and unanchored substring fallback (`"physics"` in `"biophysics"`).
19. `concierge/cycles.py:57-62,96-120` & `plan.py:23-82`: `cycle_consumption_status` queries lifetime `student_id` rows without filtering by `cycle` or `created_at >= cycle.paid_at` (locking out returning/rollover students immediately upon buying a new cycle), and `plan.py` hardcodes `AZN` pricing.

### Stage 2: Discovery, Resolver & Sweep Harness (`apps/research/`) — 16 Findings
1. `names.py:25-46` & `resolver.py:43,114,314`: Global `ae/oe/ue` replacement corrupts Spanish/French/Dutch names, and `MIN_DISTINCTIVE = 4` drops 2–3 letter Pinyin/Vietnamese tokens (`ONE_TOKEN_NAME`).
2. `names.py:31-35,71-124` & `resolver.py:60-63`: `_morph_kinds` only strips German-style tail compounds (`token[start:]`), missing head-initial Romance/Malay/Arabic compounds (`fondation...`, `yayasan...`, `al-...`).
3. `vocabulary.py:24,29-37,154,195`: `resolver_data/{CC}.json` only exists for 8 countries (`AZ, DE, GE, ID, KZ, TR, UZ, VN`), crashing with `VocabularyMissing` elsewhere; `build_country_doc` hardcodes `"ru"` and `_GEO_FLOOR = 20` / `_ORG_FLOOR = 50` (failing on small countries).
4. `wikidata.py:356,381,403-416,439`: Queries only `languages[0]` (ignoring `fr` in `BE`/`CH`/`CA`) and hardcodes `"ru"`.
5. `kind_words.py:41,104`: Drops 1-char CJK institutional suffixes (`会, 院, 部, 庁, 省`) and dotted legal forms (`e.V.`, `v.z.w.`).
6. `classify.py:103-114,204-207,240-244` & `domains.py:833-933`: Missing Global South `.edu.<cc>` / `.ac.<cc>` / `.gob.<cc>` suffixes, and `protected = True` on `.edu`/`.gov`/`.gov.scot` skips `if not protected:`, losing `verdict.country_code`.
7. `domains.py:314-320,494-812` & `providers/tavily.py:83`: `exclude_domains[:150]` silently drops the last ~140 domains of `AGGREGATOR_DOMAINS`; `STEERING` maps each country to 1 scalar language (`BE -> "nl"`).
8. `domains.py:1012-1018` & `resolver.py:141-147`: 26-domain `FREE_MAIL_DOMAINS` omits `163.com, qq.com, naver.com, orange.fr, libero.it, wp.pl, pec.it, legalmail.it`, merging unrelated foundations on Rung 0.
9. `languages.py:53,73-74`: Drops regional official languages (`ca, eu, gl`) and Maghreb higher-education French (`MA, DZ, TN`).
10. `angles.py:169-185`: `cycle_label()` hardcodes Northern-Hemisphere `2026-2027` hyphenated format.
11. `programme_angles.py:39-43,162-353`: `lang[:2]` maps `fil` (Filipino) to `fi` (Finnish); `_MONEY_WORDS` covers only 10 languages.
12. `providers/__init__.py:92-105`: `BaiduProvider` and `NaverProvider` are never registered in `default_providers()`.
13. `search.py:180-232,263` & `pipeline.py:111-128`: 16-word `FUNDING_PATH_TERMS` drops `/becas`, `/bolsas`, `/studiebeurs`, `/stypendia`, `/teqaud`, `/beasiswa`, `/hoc-bong`; and `_DEGREE_LEVEL_PATH_TERMS` rejects `/graduate/` URLs as non-Master's!
14. `national_databases.py:2384-2389` & `discovery.py:109-118`: `_FAMILY_BY_DB_KIND` emits `"FOUNDATION_SCHOLARSHIP"` instead of `"PRIVATE_FOUNDATION"`, setting `for_scholarship = False`.
15. `social_monitor.py:135,893-902,1092-1105`: `bulletin_html` truncates `[:3000]` (nav bar only), `_UNDERGRAD_ONLY_RE` matches generic Vietnamese `đại học` ("university") and Japanese `学部`, and 50-`OR` query exceeds Brave limits.
16. `winner_scraper.py:33-38,228-242,522`: English-only `_RESEARCH_SIGNAL_RE`, non-English degrees defaulted to `"BACHELOR"`, and English-only query template.

### Stage 3: Page Fetching, Readers, Scraper, Provenance & Cycles (`apps/research/`) — 18 Findings
1. `programme_scraper/extractors.py:589-596`: `resolved_year = intake_yr - 1 if d.month >= 9 else intake_yr` shifts Southern-Hemisphere and October-intake September deadlines backwards by 1 full year.
2. `cycle_verification.py:553-602`: `_step_wayback` probes at `today - k years` and caches off-season July/August `"closed"` captures (`read.returned > 0`) as `"LOOKED"`, never checking the active October–January window.
3. `cycle_verification.py:93,160-177`: Single integer `intake_start_year` collapses Spring/Fall (`Sommersemester`/`Wintersemester`, `S1`/`S2`) intakes onto one row.
4. `fetch/monitor.py:28,78-86`: Flat monthly cron (`0 6 1 * *`) misses 14–25 day scholarship windows, and `build_targets` Cartesian-products `include_paths` across all hosts.
5. `programme_scraper/extractors.py:77-121,427-434`, `specs.py:169-176`, `arbitration.py:137-154`: Missing `TRIMESTER`/`QUARTER`/`TERM` periods; and `ProgrammeQuestionSet` omits `"PER_CREDIT"`, causing Tier-1 arbitration to map `"not_stated"` -> `"ANNUAL"` and record **1 single credit hour's fee as full annual tuition**!
6. `programme_scraper/patterns.py:93-96` & `card_funding/store.py:310-315`: ECTS-only duration regex `{120: 24, 90: 18, 60: 12}`; and `store.py` ignores `first.unit == "semesters"` from `parse.py`, setting `duration_months = None` on `"4 semesters"`.
7. `programme_scraper/extractors.py:466` & `arbitration.py:194`: Hardcodes `currency="EUR"` on all `0.00` tuition-free programmes globally.
8. `funding_judge.py:149,890-902`: Excludes `"SEMESTER"` and `"TERM"` from `_AmountPeriod`, wiping out per-semester scholarship amounts (`amount = None, currency = None`) as uncountable `"OTHER"`.
9. `programme_scraper/specs.py:135,155`, `funding_reader.py:184`, `card_funding/store.py:228-232`: Hardcoded Master's-only and EU/Non-EU framing across scraper prompts and `is_servable_award`.
10. `programme_scraper/patterns.py:7-245` & `extractors.py:813-815`: 10-language ceiling on `_LANGUAGE_NAMES`; English/German-only CV/document rule regexes; and `extractors.py:814` fabricates `referee_count = "TWO"` whenever `_REFEREE_COUNT_RE` fails to match a number.
11. `programme_scraper/arbitration.py:36-55`: `needs_high_risk_arbitration` uses 100% English `_CONDITIONAL_GUARD_RE`, skipping Opus arbitration on non-English conditional tuition waivers.
12. `reader.py:136-143,199-252`: English-only `_ADMISSION_TERMS` strips non-English admission requirement sections on pages >24,000 chars whenever a single English word (`"IELTS"`) appears in the intro.
13. `funding_judge.py:51,1107,1176-1185` & `funding_reader.py:228-260`: Grouping by `(heading, kind, scope)` merges multiple scholarships under one heading and wipes their amounts (`len(found) > 1`); and sorting `"NO"` before `"YES"` causes an older intake's `"YES"` to overwrite a newer intake's `"NO"` on the same `FundingOpportunity` row!
14. `cycle_vocabulary.py:66-114` & `cycle_verification.py:650-659`: `anyascii` without `.casefold()` turns Japanese Kanji (`募集`) into Capitalized Mandarin Pinyin (`"Mu-Ji"`); `apply_links` omits `_fold(term)` for ASCII URL slugs (`/basvuru`); `_step_hop` picks navbar `candidates[0]`; `_step_search` uses an English-only query.
15. `recognition.py:299-333`: `len >= 4` drops 2–3 char CJK university names (`北大`, `연세대`) and 3-letter acronyms (`ETH`, `TUM`, `MIT`, `UCL`), and full-string substring matching fails when national registers include legal wrappers (`国立大学法人東京大学`).
16. `recognition.py:266-286,449-451,770-775`: Misses `<svg><title>` / `aria-label` logos, rejects IDNA 2008 `ß` domains via IDNA 2003 roundtrip check, and hardcodes 16 `GOVERNMENT_ZONES`.
17. `vouch.py:33-85,115-120,184-189`: 6-language hardcoded vouch vocabulary, `(?<!\w)` boundary failure on agglutinative Korean/CJK, and `www`-only `_main_host` check.
18. `blocking.py:110-120,179-189`: 100% English-only content-veto pre-filter lets non-English diploma mills and advance-fee scams bypass `Jev`.

### Stage 4: Search Tap, Candidate Pool, Evaluation & Eligibility (`apps/research/tap.py`, `spine.py`, `apps/funding/`) — 16 Findings
1. `regions.py:22-93`, `eligibility.py:113-145`, `deadline_conditions.py:90,129-138`: `REGIONS` omits `MERCOSUR, CARICOM, GCC, SAARC, SADC, ECOWAS, MENA, LATAM, NORDIC, VISEGRAD, BENELUX, EFTA, FRANCOPHONE`, and `deadline_conditions.py` ignores `_country_group_eligible_codes()`.
2. `eligibility.py:772-815`: `_decide_residence` only checks the Erasmus 12-month/5-year rule via degree year difference (`ref_year - rec_year <= 5`).
3. `facts.py:553-555`: Hardcoded 11-country `_post_study_work_countries` set.
4. `spine.py:167-219`: `_program_deadline_candidates` duplicates binary EU/EEA vs non-EU substring matching instead of calling `deadline_conditions.normalise_condition` + `validity.select_deadline`.
5. `deadline_conditions.py:36,122-138`: `_NEGATED` only checks `non[- ]$`, missing `outside [of]`, `other than`, `excluding`, `except [for]`, `without`.
6. `eligibility.py:425-495,984-1020`: `_decide_grade` fails on categorical/honours bars (`"2:1 UK Honours"`), omits Swiss `1–6`, Czech/Slovak `1–4`, Danish 7-step, and Polish `2–5` scales, and uses linear Bavarian conversion (`14/20` French -> `2.8` GPA).
7. `eligibility.py:541-696,1067-1190`: Contradiction between `_to_ielts_equiv` (`PTE 65 / Duolingo 125 -> C1`) and `_level_to_cefr` (`PTE 70 / Duolingo 125 -> B2`), plus `UNDECIDABLE` on numeric scores for 25+ non-English exams.
8. `eligibility.py:222-283`: `_DEGREE_WORDS` omits `B.Tech`, `M.Tech`, `B.E.`, `B.Com`, `Laurea Triennale`/`Magistrale`, `Licenciatura`, `Maestría`, `Mestrado`, `Diplôme d'Ingénieur`.
9. `eligibility.py:295-306,1026-1065`: `WORK_EXPERIENCE` disallows `LTE` caps and returns `UNDECIDABLE` on `unit == "HOURS"` (Chevening 2,800h) even when `months == 0`.
10. `eligibility.py:1192-1209`: `_decide_age` evaluates age at `today` instead of `intended_intake` and treats `"under 30"` as `<= 30`.
11. `pool.py:169`, `tap.py:1132`, `tap_query.py:100-105`: Hardcoded `degree_level="MASTER"` and Eurocentric `"60 ECTS"` / `"120 ECTS"` queries.
12. `facts.py:429-633` & `evaluation.py:68-69,266-267,745`: 15-month Master's classified as `TWO_YEAR`; `RESEARCH_FIT` drops to `50 < 60` (`_BALANCED_DIMENSION_BAR`) on general degree titles; `ACADEMIC_FIT` ignores GPA.
13. `spine.py:98` & `pool.py:308-341`: Unstratified `POOL_LIMIT = 50` starves smaller destination countries and alphabetically later `HOLDER` awards.
14. `spine.py:617-618`: Hardcoded `25%` fallback selective-funding probability when `effective_award_pcts` is empty.
15. `hybrid_strategy.py:183-189` & `tap.py:613-618,830-836`: Country-size-blind `min_programs_per_country = 5` / `deep_saturation_count = 15` and sequential country loop where one saturated country trips `self.plateaued` for all remaining countries.
16. `tap_query.py:231-240`: Uses only `teaching_languages[0]` and truncates `money_words[:2]`.

### Stage 5: Transcript Eligibility §§3–7, Pack Portfolio, Affordability & FX (`apps/funding/`) — 18 Findings
1. `transcript_eligibility.py:4229-4234,4829-4837`: `"First Class"` collision between UK First-Class Honours (`1.5` Bavarian) and Indian/Commonwealth First Class (`2.5` Bavarian).
2. `transcript_eligibility.py:4562-4574,170-190`: Country-blind `_STATUTORY_SCALE_BOUNDS` (French `14/20` -> `2.8` GPA; Canadian/Korean `4.0/4.3` -> `3.73` GPA; Czech/Slovak `1–4` and Filipino `1–5` inverted scales treated as ascending).
3. `transcript_eligibility.py:5121-5139,5247-5268`: Off-by-`0.2` Bavarian penalty (`bav_rec <= bav_bar - 0.2`) demotes exact/better grades (`2.4` vs `2.5` bar) to `BORDERLINE` (`-3` penalty in `pack.py:330`).
4. `transcript_eligibility.py:4214-4221,5171-5183`: `_GPA_BAR_RE` drops unstated-denominator bars in `(4.0, 50.0)` (`"CGPA of 7.5"`, `"average of 14"`).
5. `transcript_eligibility.py:4713-4758`: `_infer_unstated_scale` misclassifies `KZ/UZ/NG` `5.0`-scale grades as `4.0` and `CZ/SK` inverted grades as ascending `4.0`.
6. `transcript_eligibility.py:3141-3168,3290`: `_TOTAL_DEGREE_CREDITS_RE` only matches `(180|210|240)` and `"semester"` in `"30 ECTS semester credits"` triggers `2x` US conversion (`60 ECTS`).
7. `transcript_eligibility.py:3183-3253`: Regex character ranges omit French/Spanish/Nordic/Slavic accented letters (`É, è, ł, ś, č`).
8. `transcript_eligibility.py:3741-3913`: Sequential Stage 2a (`min_ects`) before Stage 2b (`min_courses`) can drain shared courses needed by `min_courses` buckets.
9. `transcript_eligibility.py:4294-4298,4337-4352,5351-5398`: `_GMAT_BAR_RE` (`[4-8]\d0`) rejects GMAT Focus Edition scores ending in `5` (`615`, `645`).
10. `transcript_eligibility.py:4263-4293,5881-6298`: 7-country `anglophone` MOI waiver set and scalar `min(subscores)` IELTS check (failing `"6.5 in Writing and 6.0 in others"`).
11. `transcript_eligibility.py:4299-4316,5404-5520,5757-5786`: Ignores `post-graduation` work filter, ordinal dates (`1st September`), `intended_intake` recency anchor, and `country_of_residence` for EU visa deadlines.
12. `pack.py:47-55,462-550,772-929`: Greedy 1D traversal fails on fee-budget knapsack tradeoffs and ignores correlated funding failure across programmes sharing the same external scholarship.
13. `pack.py:314-315`: `top_only` adds `(50 - eff_chance) * 0.15`, rewarding low personal admission probability as a proxy for prestige!
14. `pack.py:879,919`: Checks `fee_in_base * BANK_MARGIN <= budget_remaining` but deducts `fee_in_base` without `BANK_MARGIN`.
15. `affordability.py:20,116-153`: Scales `ANNUAL` tuition by `duration_months / 12` (understating a 9-month Master's annual tuition by `25%`) and allows category-restricted benefits to cross-subsidize other cost categories.
16. `reference_data.py:38-46`, `fx.py:57-58`, `rates.py:51`: `rates.py` only bridges cross-rates when `base == "AZN"`.
17. `validity.py:233,252`: Hardcodes `_ASSUMED_INTAKE_START = (9, 1)`, misclassifying a `15 Sept` German deadline (for a `1 Oct` start) as next year's intake.
18. `grouping.py:66-74`: Blocks outbound national scholarships (`HOLDER`/`COUNTRY` in `home_country`, e.g. `AZ` DP, `KZ` Bolashak, `TR` YLSY) from grouping under foreign destination programmes.

### Stage 6: OCR, Transcript/ID/Certificate Reading, PII & Evidence (`apps/documents/`) — 18 Findings
1. `transcript.py:54-64,293-339`: 4-language `_PERSONAL_LABEL` (`en/tr/az/ru`) and `len(hits) >= 2` in `_names_in` leak French/German/Spanish/Italian/Arabic/CJK metadata and split-line student names (`Nom: Dupont` / `Prénom: Jean`) to Jev.
2. `transcript.py:67,359,392`: `_ID_NUMBER = re.compile(r"\d{6,}")` deletes entire university header lines containing 6-digit postal codes and masks 6-digit course codes (`5710111`) to `#`.
3. `transcript.py:68-70,402-417`: `_DATE` ignores written-month dates (`16 May 2025`) and hardcodes `day, month, year` (`DMY`), misparsing US `05/12/2025` as Dec 5 or dropping `05/16/2025`.
4. `transcript.py:703-704`: `text.partition(":")` strips `"University of California:"` from `"University of California: Berkeley"` and misses CJK fullwidth `：`.
5. `transcript.py:195-212`: `_fold` only maps `ı -> i` and `ə -> a`, missing `ł, ß, ø, æ, đ` and non-Latin scripts.
6. `transcript_pages.py:139,179-183`: `_LANGUAGES = frozenset({"az", "tr", "ru"})` refuses registration of any transcript in `de, fr, es, it, zh, ar`, etc.
7. `transcript_pages.py:74-93,225-240`: `is_english(page)` only checks Cyrillic share and 28 Turkish/Azerbaijani words, treating French/German/Spanish/Chinese/Arabic original pages in a bound `TRANSLATION` PDF as English and **duplicating every course**.
8. `transcript_checks.py:92-96`, `transcript_questions.py:211-215`, `transcript.py:706`: Assumes higher numbers mean better grades (breaking German/Austrian/Philippine inverted `1.0–5.0` scales) and drops non-numeric overall grades (`First Class Honours`, `Mention Très Bien`).
9. `credits.py:72-99,129-150`: `_MASTER_QUAL_RE` only knows 4 languages (misclassifying `Laurea Magistrale`, `Diplôme d'ingénieur`, `LL.M.`, `MBA`, `M.Tech`, `硕士` as Bachelor's = 180/240 ECTS instead of 120 ECTS!), and `_THREE_YEAR_BOLOGNA_COUNTRIES` / `_FOUR_YEAR_BACHELOR_COUNTRIES` only cover 29 countries (and put Spain `ES` in 3-year 180 ECTS when a Spanish *Grado* is 4 years / 240 ECTS).
10. `transcript_checks.py:109-126`: `_mixed` only checks `{"LATIN", "CYRILLIC"}`, missing Greek-Latin OCR homoglyphs.
11. `id_reading.py:278-334`: `_owner_matches` requires `given_words[0]` to match (rejecting compound given names where the student uses their second given name, e.g. `"Marie Jean Dupont"` -> `"Jean Dupont"`), requires non-empty `surname_words` (rejecting Indonesian/Indian mononyms), and omits `bin`/`binti`/`ibn` patronymics.
12. `mrz.py:265-291`, `text_reading.py:128-174`, `id_reading.py:337-366`: `mrz._keys` does not transliterate non-Latin scripts (`anyascii`), rejecting native-script Cyrillic/Greek/Arabic/CJK diplomas as `owner_mismatch` AND leaking non-Latin names to OpenRouter.
13. `text_reading.py:37-64`: `_TEST_ALIASES` (13 tests) and `_RANGES` (4 tests) reject `Goethe-Zertifikat`, `telc`, `DSH`, `ÖSD`, `TCF`, `TEF`, `DELE`, `SIELE`, `CILS`, `CELI`, `TÖMER`, `TORFL` as `unknown_test`.
14. `dates.py:69-104` & `text_reading.py:192-219`: `dates.py` only has 5 languages of month names, and `_iso_date` fails to split East Asian dates (`2025年6月18日`, `2025년 6월 18일`).
15. `evidence/signals.py:55,142-180,329-341,406-445`: Only parses `.py`/`.ipynb` and 5 manifests (ignoring `pyproject.toml` and all C/C++, Rust, Go, TypeScript, Java, R, Julia source files), causing non-Python repos with short READMEs to fall below `EVIDENCE_FLOOR` and be deleted!
16. `evidence/repo.py:24-26,203-204`: Rejects `gitlab.com` and `huggingface.co` repos.
17. `evidence/publication.py:157-220`: `_extract_raw_surname_token` assumes surname is `parts[-1]`, rejecting East Asian / Hungarian uncomma'd surname-first author strings (`"Zhang Wei"`) and Hispanic double surnames (`"Juan Pérez Gómez"`).
18. `evidence/intake.py:246-256` & `refresh.py:200-203`: Scanned thesis PDFs (`< 500` chars in `pypdf`) are deleted without OCR fallback on title/abstract/TOC pages.

### Stage 7: CV, Letters, Gates, Storyline, Research Fit & Referee Package (`apps/documents/`) — 21 Findings
1. `research_fit/anchors.py:30-31,180-182`: `[A-ZÀ-ÝĞİÖÜŞÇ]` omits Polish/Czech/Hungarian/Baltic/Azerbaijani (`Ł, Ś, Č, Ř, Š, Ž, Ő, Ű, Ə`) and Cyrillic uppercase letters, leaking unverified faculty names into search queries in `guard_phrase()`.
2. `research_fit/classify.py:77-85`: English/German-only `_INACTIVE_PERSON_RE` recommends retired/emeritus/visiting faculty on French (`Professeur émérite`), Dutch (`met emeritaat`), Italian (`fuori ruolo`), Spanish (`jubilado`), Turkish (`emekli`), and CJK pages.
3. `research_fit/papers.py:50-75,299-345`: Fragmented title/trainee/name matcher misses European titles (`Univ.-Prof.`, `Prof.ssa`, `Dott.ssa`, `Priv.-Doz.`, `Ir.`) and family-name-first order (`Kovács János`, `張偉`).
4. `research_fit/papers.py:77-85` & `anchors.py:365-373`: English-only `_WORK_PHRASE_CUE_RE` and raw surface-token overlap in `infer_fit_mode` (misclassifying all non-English university page sentences as `"method_transfer"`).
5. `research_fit/anchors.py:55-59`: 1:1 `_SITE_LANGUAGE` maps `CH -> "de"` (firing German queries for EPFL/UNIGE) and `BE -> "nl"` (Dutch queries for UCLouvain/ULB).
6. `research_fit/split.py:19-30`: `_BOUNDARY` fails to split CJK sentences (`。！？`) or sentences starting with `Ł, Ś, Č, Ə, А-Я`.
7. `research_fit/home_context.py:47-119,310-313`: 8-bucket English keyword matcher and hardcoded English `"World Bank"` sentence template (which fails `sourced_claim_matches` when translated into `"Weltbank"` or `"Banque mondiale"` in a German/French letter!).
8. `table.py:56-75`: English-only `_WORDS` and `_CERTIFIED` regexes mark non-English kit requirements (`Motivationsschreiben`, `Relevé de notes`, `beglaubigt`) as `NOT_NEEDED`.
9. `europass.py:276-307,331-348`: 30-language `_LANGUAGE_CODES` dict raises `EuropassUnavailable` and aborts the entire Europass CV render on unlisted (`Uzbek`, `Armenian`, `Vietnamese`) or native-named (`Deutsch`, `Français`, `Türkçe`) languages.
10. `render.py:61-70`: `_TABULAR_INSTITUTIONS` only lists `ch:eth zurich`, routing UZH, Basel, Bern, and St. Gallen to `ACADEMIC` instead of DACH `TABULAR`.
11. `catalog_seed.py:82-720`: Seeds only 20 of ~216 researched rules in `docs/research/*.csv`.
12. `letter_gates.py:117-159,424-478` & `letter_verification.py:133`: `capitalised_phrases` treats every 2+ capitalized word run as a proper-noun entity, blocking valid German (`de`) letters where all nouns are capitalized (`"Praktische Arbeit"`, `"Ihr Masterprogramm Informatik"`).
13. `letter_gates.py:94-97`: English-only month names in `_DATE_PATTERN`.
14. `letter_gates.py:239-247,590-604`: Incomplete multilingual title/group/programme-offering vocabularies (`Univ.-Prof.`, `Prof.ssa`, `Laboratoire`, `vakgroep`).
15. `letter_gates.py:742-830`: English-only `_AI_PARTICIPIAL_TRAILER_RE` / `_AI_CLOSING_SUMMARY_RE` and space-split sentence length (`s.split()`) on CJK (`zh`/`ja`).
16. `letters.py:710-775`: 15-language `_DOC_LANG_ALIASES` (missing `es, pt, pl, cs, hu, ar, az`) and English-only test-name inference (missing `TestDaF`, `DELF`, `DELE`, `JLPT`, `TOPIK`, `HSK`, `TÖMER`).
17. `storyline.py:296-313`: `choose_opening_kind` branches only on `cc in {"GB", "UK"}` instead of the resolved lettering system (`COUNTRY_SYSTEM`).
18. **`referee_package.py:454` (`mask_pii_for_referee_llm` — CRITICAL):** Masks any 3+ letter name substring (`len(raw_val) >= 3`) **without word boundaries (`\b`)**, corrupting `"analytical"` -> `"an[CANDIDATE_NAME]tical"` -> `"anAli Aliyevtical"` and `"qualified"` -> `"quAli Aliyevfied"` whenever a student or referee is named `Ali`, `Can`, `Lee`, `Kim`, `Dan`, `Max`, `Eva`, `Ian`, `Roy`, `May`, `Han`, or `Son`!
19. `referee_package.py:100-103,472`: `_DOUBT_RAISERS_RE.sub("is", cleaned)` turns `"Despite initial struggles, X mastered..."` into ungrammatical `"is, X mastered..."`.
20. `referee_package.py:63-91`: 26-domain `_WEBMAIL_DOMAINS` misses regional consumer webmail (`orange.fr, t-online.de, libero.it, wp.pl, seznam.cz, naver.com, 163.com, qq.com, ukr.net, mail.az`).
21. `referee_evidence.py:312-359,879-960,1302-1340`: English-only relationship classification and course stopwords misclassify non-English thesis advisor descriptions (`"Bitirme tezi danışmanım"`, `"Betreuer meiner Bachelorarbeit"`, `"Научный руководитель"`) as `"course_instructor"`.

### Stage 8: Portals, Browser Extension, Mailbox Signals & Dashboard (`apps/portals/`, `apps/mailbox/`, `apps/dashboard/`, `extension/`) — 23 Findings
1. `extension/src/content/vocabulary.ts:22-238` & `verify.ts:55-101,156-160`: `normalise()` strips all non-ASCII characters (`[^a-z0-9]`) and `TOKENS` only covers 5.5 languages, causing `verifyEntries()` to reject 100% of LLM-learned (`LearnFieldMap`) form fields on Dutch, Italian, Polish, Russian/Cyrillic, CJK, and Spanish portals at runtime!
2. `extension/src/content/fill.ts:99-165`: `OPTION_SYNONYM_GROUPS` only has 5 countries and zero `F`/`M` sex/gender synonyms (so `identity.sex = "F"` fails to match `<option>Female</option>` or `<option>Weiblich</option>`).
3. `extension/src/content/snapshot.ts:86-106` & `apps/portals/packets.py:332-373,419-424`: `inferredMaxLength` multiplies word limits by `words * 5` (`500 words -> 2500 chars`), causing `packets.py` to chop valid 450-word essays (~3,000 chars) down to ~370 words!
4. `extension/src/content/fill.ts:281-309,381-393` & `vocabulary.ts:279-291`: `KIND_TERMS` is English-only and `DOC_TOKENS` omits French (`Relevé de notes`, `Passeport`), Azerbaijani, Dutch, Italian, Spanish, and Polish, downgrading automatic file uploads to `manual`.
5. `extension/src/content/snapshot.ts:12-21,180-183` & `verify.ts:135-140`: Hard-blocks `input[type="radio"]` and WAI-ARIA `role="combobox"` controls used across Workday, Slate, DreamApply, and Mobility-Online.
6. `extension/src/content/code.ts:23-54`: `NOT_CODE_WORDS` blocks `"Security code"` even when no password input is on the page, and `boxes.length === 1` fails on 6-box split OTP inputs (`maxlength="1"`).
7. `extension/src/content/page_signals.ts:44-49`: English-only regex for `application_number` extraction (`Bewerbungsnummer`, `Numéro de dossier`, `Başvuru No` missed).
8. `apps/portals/prepare.py:64-85,110-148`: `_folds()` rejects any non-Latin character in `identity.full_name` with `reason="name_unsafe"`, failing to rename upload files even when ICAO ASCII passport MRZ names exist.
9. `apps/portals/rules.py:12-40`: `_FORMATS` omits `"YYYY"` (year-only) and `"DD-MM-YYYY"`.
10. `apps/portals/profile.py:40-43,128-130`: `_degree_order` sorts undated entries (`""`) **first** (`education.1` / `experience.1`) and sorts oldest-first for `experience.1`.
11. `apps/portals/credentials.py:29,64-93`: English-only `_NO_SYMBOLS_RE`, 4-language `_RANGE_CAP_RE`, and fixed `_SYMBOLS = "!#"`.
12. `apps/portals/outcome.py:42-47` & `reminders.py:341,408,456`: Notification auto-acknowledgement and deduplication query hardcoded English message substrings (`message__startswith="Have you heard back from "`).
13. `apps/mailbox/filter.py:361-374`, `sync.py:262,553`, `actions.py:368-395`: When a student has 2+ applications on the same university or central portal host (`tum.de`, `uni-assist.de`, `ucas.com`, `studielink.nl`), `vouched_senders` sets `senders[host] = None` and `sync.py:262` **completely skips `read_decision()` (`Jev`)**, even when the email body contains the exact `application_number` and `offered_programme`!
14. `apps/mailbox/decision_reader.py:42,64-80`: Word-level `strip_identifiers` replaces `"can"` -> `"[name]"` for a student named `Can`, `"may"`/`"june"` for `May`/`June`, or university names (`Humboldt`, `Koç`, `Ada`), and `_PHONE_RE` masks 9+ digit `application_number` IDs to `"[phone]"` before `Jev` reads the email.
15. `apps/mailbox/decision_reader.py:86-98`: Exact contiguous substring check (`_norm(phrase) in _norm(body)`) drops spans containing soft hyphens (`\u00ad`), line-wrap hyphens, or agglutinative suffixes.
16. `apps/mailbox/filter.py:91-163`: `_FREE_MAIL_DOMAINS` (20 domains) misses regional consumer webmail (`yahoo.co.uk`, `bk.ru`, `box.az`), and `_SHARED_PLATFORMS` misses `mobility-online.com`, `fullfabric.com`, `studielink.nl`, `parcoursup.fr`, `ucas.com`.
17. `apps/mailbox/providers.py:363-387,425`: `if '"' in auth_results:` on line 425 rejects any RFC 8601 `Authentication-Results` header with quoted pvalues (`header.from="uni.de"`) *before* calling `_without_comments_and_quotes(auth_results)`!
18. `apps/mailbox/providers.py:477-486,706-711`: Extracts only the first `To` header, ignoring `Delivered-To`, `X-Original-To`, `Cc`, and `Bcc` (breaking `+tag` matching on bulk `Bcc` admissions emails).
19. `apps/mailbox/actions.py:33,415-418`: `_FORMATTED_CODE_RE` requires `{2,6}` chars per group, dropping spaced single-digit OTP codes (`"1 2 3 4 5 6"`).
20. `apps/mailbox/decision_bars.py:11-12`: Hardcodes `MEASURED_ON = ""` and `BARS = {}` in Python source.
21. `apps/dashboard/templatetags/dashboard.py:159-176`: `programme_in_university` rewrites every degree (`MA`, `LL.M.`, `MBA`, `BSc`, `PhD`) as **`"MSc in {field}"`**!
22. `apps/dashboard/mylist.py:362-425,527-537`: `plain_reason()` formats failed conditions (`outcome == "FAILED"`) with positive text: **"Your grade of 75 on a 100 scale meets the 80 required"** right underneath `"You don't meet this yet"`!
23. `apps/dashboard/money.py:78`, `dates.py:43-50`, `mylist.py:238-268`: Hardcodes `"CBAR"` in `rate_note`, displays `"23:59 London time"` for un-timed dates, and reads only `academic_history[0]` / `language_evidence[0]`.

---

## Top 10 Consolidated High-ROI `scilit` Research & Code-Port Targets

1. **Direct Code Port from `scilit.synthesis.humanize` & `scilit.synthesis.write` (`apps/documents/letter_gates.py`, `letters.py`, `referee_package.py`, `letter_verification.py`)**
   - Port `FactInvariantGate`, `EditorialPipelineValidator`, `EmpiricalSurprisalScorer`, `ScientificHumanizer`, `audit_understandability` (Gopen & Swan subject-verb gap + `find_orphan_acronyms`), and `normalise_numerals` directly from `/home/orkhan/code/scilit/src/scilit/synthesis/humanize.py` and `write.py`.
2. **Simultaneous Application Portfolio Optimization under Fee Budget & Correlated Funder Risk (`apps/funding/pack.py`)**
   - Replace greedy 1D pack selection with Chade & Smith (2006) Marginal Improvement / Sviridenko (2004) submodular knapsack optimization accounting for shared external scholarship correlation (`HOLDER`/`COUNTRY` awards).
3. **International Grading Scale Equipercentile Conversion & Global Language-Exam Psychometric Concordance (`apps/funding/eligibility.py`, `transcript_eligibility.py`, `apps/documents/credits.py`, `transcript_checks.py`)**
   - Replace linear Bavarian interpolation and contradictory IELTS/CEFR tables with ECTS/WES/Nuffic non-linear percentile conversions, directional scale bounds (supporting inverted `1.0–5.0` scales and UK vs Indian First Class), and published psychometric concordance intervals across 30+ global language exams.
4. **Dawid-Skene / Bayesian Truth Discovery & Conformal Risk Control for Multi-Reader Arbitration (`apps/research/programme_scraper/arbitration.py`, `funding_judge.py`, `apps/mailbox/decision_bars.py`)**
   - Replace unweighted 3-of-3 voting, English-only Opus triggers, and uncalibrated verbalized LLM confidence bars with cost-sensitive Bayesian truth discovery and Risk-Controlling Prediction Sets (RCPS / Clopper-Pearson upper confidence bounds).
5. **Cross-Script Institutional & Personal Name Entity Resolution (`apps/research/names.py`, `resolver.py`, `recognition.py`, `apps/documents/id_reading.py`, `mrz.py`, `publication.py`, `research_fit/papers.py`, `apps/portals/prepare.py`)**
   - Unify ICAO Doc 9303 / ISO 9 / CLDR / `anyascii` transliteration, East Asian/Hungarian surname-first rotation, Hispanic double surnames, compound given names, mononyms, and Fellegi-Sunter / SoftTFIDF institutional record linkage.
6. **Mark-Recapture Unseen-Species Stopping & Hazard-Guided Seasonal Renewal Scheduling (`apps/research/harness.py`, `tap.py`, `cycle_verification.py`, `fetch/monitor.py`)**
   - Use `state.recaptured` for Chao1 / Good-Turing coverage estimation in search sweeps, and seasonal renewal / hazard-rate scheduling for Wayback probing and dynamic monitor crons.
7. **Context- & Layout-Aware Multilingual PII Redaction Without Entity/Code Corruption (`apps/documents/transcript.py`, `referee_package.py`, `apps/mailbox/decision_reader.py`)**
   - Separate header vs table zones on transcripts, enforce word-boundary/capitalization/homograph guards on short names (`Ali`, `Can`, `May`), and protect 6–7 digit course codes and 9–10 digit application numbers.
8. **Cross-Lingual Web Form Control Verification & Extractive Span Grounding in Agglutinative Languages (`extension/src/content/verify.ts`, `vocabulary.ts`, `apps/mailbox/decision_reader.py`)**
   - Replace ASCII-only `normalise()` and the 5-language `TOKENS` blocklist with Unicode `\p{L}\p{N}` + learned label fingerprints + multilingual prototype tokens, and add soft-hyphen/inflection-tolerant span grounding.
9. **MAUT Preference Polytope Barycenter Weight Inference & Conjunctive-Compensatory Fit Scoring (`apps/accounts/schemas.py`, `apps/funding/evaluation.py`, `facts.py`)**
   - Infer personalized 7-simplex weights $\mathbf{w} \in \Delta^6$ from categorical onboarding answers (`career_intent`, `funding_dependency`, `duration_preference`) via the analytic center / Dirichlet mean of the preference polytope, and replace hard min-bar cliffs with a conjunctive-compensatory power mean.
10. **Polyglot Source-Code Signature Extraction & Adaptive Perceptual Document Compression (`apps/documents/evidence/signals.py`, `apps/portals/prepare.py`)**
    - Expand repository signal extraction beyond Python to `pyproject.toml`, Rust, Go, TypeScript, C/C++, Java, R, and Julia, and replace fixed 3-step JPEG downsampling with binary-search rate-distortion / grayscale adaptive compression for scanned PDFs.
