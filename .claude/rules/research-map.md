---
paths:
  - "apps/research/**"
  - "tests/research/**"
---

## Research area map: where the search engine lives

<!-- A map, not rules: it says where to look so a session or subagent does not rediscover the layout by grep.
Checked against master e5258ea2 (2026-10-24). When a file named here moves or is renamed, fix its line. -->

How the whole engine works, with measurements and status: `docs/superpowers/2026-10-24-search-engine-how-it-works.md`
(sections named below as "doc §N"). Read the doc before exploring code to explain the engine; read the code to check it.

Big files (over 900 lines): outline first with `grep -n "^def \|^class "`, then read ranges:
`national_databases.py` (2,940), `models.py` (1,764), `funding_judge.py` (1,330), `social_monitor.py` (1,293),
`tap.py` (1,201), `spine.py` (1,193), `pipeline.py` (1,043), `domains.py` (1,034), `cycle_verification.py` (1,010), `recognition.py` (958).

**Offline, shared catalogue** (doc §2–6), in pipeline order:
- Register, the one door in: `register.py::record_organisation`; domain key: `hosts.py`, `domains.py`.
- Lists and enumerators: `closed_lists.py`, `vgm.py`, `wikidata.py`, `eacea.py`, `ror.py`, `national_databases.py`.
- Name → website: `resolver.py` (rules data in `vocabulary.py`, `names.py`, `resolver_data/`), written by `resolve_entries.py`; hold-out test `holdout.py`.
- Host classifier: `classify.py`. Sweep harness: `harness.py::run_pass`, with `angles.py`, `programme_angles.py`, `languages.py`, `kind_words.py`, `tally.py`, `coverage.py`, `cells.py`.
- Search providers: `providers/` (Exa, Brave, Tavily, Diffbot, Baidu, Naver). Lead discovery: `discovery.py`, `pipeline.py::run_discovery`, `search.py`, `seeds.py`, ministry/Telegram pointer monitor `social_monitor.py` (`poll_ministry_channels`), PII-free LinkedIn cohort aggregator `winner_scraper.py` (`sync_winner_cohorts`); the only DB writer is `catalog.py`.
- Fetch ladder (doc §3): `fetch/__init__.py::fetch_page`, rungs in `fetch/firecrawl.py`, `fetch/scrapedo.py`, `fetch/archive.py`; site jobs `fetch/site.py`, `sitejob.py`; safe HTTP `egress.py`.
- Readers (doc §4). Gen-1, live: `funding_judge.py`, `funding_reader.py`, `reader.py`, `decisions.py`, and structured/LLM programme scraper `programme_scraper/` (`programme_scraper/orchestrator.py::scrape_fetched_programme_page`, `programme_scraper/orchestrator.py::scrape_programme_pages`, `programme_scraper/extractors.py`, `programme_scraper/arbitration.py`, `programme_scraper/persistence.py`, `programme_scraper/sublinks.py`). Gen-2 card engine, not wired:
  `card_funding/entry.py::read_page`, `card_funding/hunt.py::hunt_card`, `card_engine/`, `candidates/`; its measurement harness `engine_eval/`.
- Provenance gate (doc §5): `provenance.py` (verdicts), `provenance_job.py` (checks), `recognition.py`, `vouch.py`, `blocking.py`, `rdap.py`, `jev.py`; reaching published packs: `provenance_sweep.py`.
- Freshness (doc §6): `cycle_verification.py::verify_cycle`, `cycle_vocabulary.py`, `fetch/monitor.py`, `metering.py`.
- Operator queue: `resolution/` (`resolution/writers.py` is the only code that adds or withdraws an item).

**Per student** (doc §7–8):
- Worker: `management/commands/run_research_worker.py` → `services.py::handle_research_message` → `spine.py::build_student_pack`
  (pool → facts → evaluate → probability → pack, in `apps/funding/`, see `funding-map.md`) → `services.py::_publish`.
- The tap: `tap.py::run_tap` (`request_tap`, `on_profile_saved`), 3-tier sufficiency gate `hybrid_strategy.py`, queries `tap_query.py`, money `wallet.py`,
  interfaces `tap_seams.py`, bindings `seam_bindings.py`.

Models (`models.py`): `Organisation`, `OrganisationDomain`, `RegisterEntry`, `HostProfile`, `FetchAttempt`, `DecisionRecord`,
`ProvenanceVerdict`, `SweepRun`, `SweepAngle`, `AreaSweep`, `SearchWallet`, `SearchTap`, `CellCoverage`, `ResolutionItem`, `WinnerCohortProfile`.
Catalogue rows (`Program`, `FundingOpportunity` …) live in `apps/funding/models.py`.
Commands: `management/commands/` (55; the name says the job, such as `sweep_organisations`, `provenance_check`, `cycle_verify`, `run_first_search`, `poll_ministry_channels`, `sync_winner_cohorts`).
Tests: `tests/research/` (155 files), usually `test_<module>*.py`; when none matches, `grep -rl "<module>" tests/research`.
