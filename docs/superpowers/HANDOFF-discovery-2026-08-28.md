# Handoff — funding-led discovery, 2026-08-28

## Resume Prompt

> This handoff is the source of truth for what happened. If `claude-mem` injects
> observations for tehsil_agent, treat them as supporting recall only; missing,
> empty, stale or wrong-project memory is not a blocker and should not be chased.
> Worktree `/home/orkhan/Desktop/tehsil_agent`, branch
> `claude/phase-5-automated-discovery-requirements`, HEAD should be `d03783b`.
> First action, read-only: `git log --oneline -5` and read
> `docs/superpowers/specs/2026-08-28-funding-led-discovery-design.md`. External
> blocker: three items are waiting on the user (a research run, two
> registrations, and ten domain questions) — do not attempt them. Do not re-run
> the deep research, do not re-probe the source landscape, and do not run a
> shadow discovery unless asked.

## 1. Goal

Make the Phase 5 discovery engine actually discover something. It shipped
correct and produced **zero catalog rows**. The work was finding suppliers of
leads, not changing the pipeline.

## 2. Memory assumption

Assume nothing was preserved. Everything needed is in this file, in the four
committed docs named below, and in git history from `3876b81` to `d03783b`.

## 3. Decisions made

- **Discovery is funding-led**, not catalogue-led: grant/registry sources yield
  organisations, entity expansion resolves them to origin pages.
- **Discovery runs worldwide; country is an output, not a filter.** `--country`
  survives as a results filter that never reaches a `LeadSource`. Rationale:
  destination is the dominant correlation axis in the portfolio model, so a
  country-filtered run cannot build the reach-and-safety portfolio.
- **Coverage is an optimizer outcome rate, not a catalog count and not a human
  gate.** The student's fee budget is a parameter of the optimisation, so no
  per-corridor constant can answer "is this enough". Serve flags and thresholds
  were specced and then deleted.
- **`robots.txt` is no longer a retrieval constraint** (user decision).
  Published access terms remain binding. Recorded with the distinction stated.
- **CORDIS and KAKEN dropped**: they fund doctoral/postdoc research, not
  master's. ANR survives as the only confirmed master's-funding grant source.
- **China MOE: build despite silent terms** (user decision). ROR is the cheaper
  route and is recorded alongside.
- **P1-7.1 amended**: official source URLs are internal-only, not shown to
  students. "Internal" defined as platform + tenant counselors.
- **EACEA leads the build order** — needs no registration, email or key.

## 4. Files changed

Code:
- `apps/research/harvest.py` — new `content_digest()`, stdlib boilerplate strip
- `apps/research/egress.py` — `_SHELL_MIN_BYTES` 20_000→2_000; address-family
  fallback in `_request`
- `apps/research/pipeline.py` — content-digest revalidation shortcut
- `apps/research/snapshot.py`, `apps/funding/models.py`,
  `apps/funding/migrations/0014_officialsourcesnapshot_content_sha256.py`
- `apps/research/seeds.py` — `HtmlCatalogue` gains `exclude_suffix` /
  `source_type`; EACEA config rewritten
- `apps/research/domains.py` — social hosts added to `CATALOGUE_DOMAINS`
- Tests: `tests/research/test_harvest.py`, `test_egress.py`,
  `test_discovery_pipeline.py`, `test_seed_sources.py`

Docs:
- `docs/superpowers/specs/2026-08-28-funding-led-discovery-design.md` (main spec)
- `docs/superpowers/2026-08-28-discovery-state-of-play.md` (frame + reasoning audit)
- `docs/superpowers/research/2026-08-28-worldwide-funding-sources-{review-1,review-2,synthesis}.md`
- `phased requirements.md` — P1-7.1 amendment

Pre-existing dirty files, untouched and not mine: `CLAUDE.md`, `DESIGN.md`,
`.agents/product-marketing.md`, `docs/tehsil-website-marketing-spec.md`,
`skill-observations/`, `website-proposal.md`.

## 5. Commands/checks run with results

- `POSTGRES_DB=tehsil_specwork uv run pytest tests/research/ -q` → **217 passed**
- `uv run ruff check apps tests` → All checks passed
- `uv run mypy apps` → Success, 133 files
- `uv run bandit -c pyproject.toml -r apps` → No issues identified
- Full suite: **68 failures, all `TemplateDoesNotExist`** — pre-existing, the
  `templates/` directory was deleted before this session. Verified against a
  stashed baseline; not caused by this work.
- Live EACEA harvest: **169 `PROGRAM` leads**, 0 europa.eu, 0 social, all
  claim-capable.

## 6. Remaining work

Waiting on the user, do not attempt:
1. ~~Corridor round-2 deep research.~~ **DONE 2026-08-28.** Both runs filed as
   `research/2026-08-28-corridor-mechanics-round2-review-{1,2}.md` and
   synthesised; `2026-08-27-risk-aware-portfolio-design.md` amended, open items
   1 and 3 closed. Residual verification only, listed in that spec's §14 item 5.
2. Register `data.go.kr` (dataset **#15107736**) and note the daily call cap.
3. Email Opetushallitus re the `konfo-backend` licence.
4. Answer ten questions about the Azerbaijani outbound state scholarship — these
   block two known spec defects (below).
5. DNS for `tehsil.app` plus a page at `/bot`.

Engineering, when asked:
- Shadow run against the 169 EACEA leads (user explicitly deferred it).
- `RegistrySource` Korea, then Finland; `OrganisationFrame` over ROR; ANR.
- Index-page harvest for RWTH-class sites; discipline taxonomy for coverage rates.

## 7. Blockers/risks

- **Two known defects in `docs/superpowers/specs/2026-08-27-risk-aware-portfolio-design.md`,
  deliberately unamended**, waiting on item 4: the Azerbaijan instrument row
  conflates the outbound state programme with the inbound Heydar Aliyev grant,
  and §7.4 bars "Azerbaijan" from ever being a floor on the strength of the
  *inbound* grant — wrong for the primary student population.
- `tehsil.app` does not resolve, yet every crawl advertises `+https://tehsil.app/bot`
  as the contact URL.
- The user asked for a browser-impersonation stack to defeat EACEA's 403; I
  declined and found the legitimate route instead. It is in **Not built**.

## 8. Do not redo

- The two deep-research runs — filed as `-review-1` / `-review-2` and synthesised.
- The source-landscape probes — CORDIS, OpenAIRE, ROR, UKRI, Italy, Swecris,
  Korea, KAKEN, NSFC, EACEA. Results are in the synthesis §7.
- The census-frame / ETER investigation. Dropped with reasons; do not re-propose.
- Coverage thresholds and per-corridor serve flags. Specced, then deleted.
- CORDIS and KAKEN adapters. Dropped on merit.
- **Do not extrapolate a source's contents from a total count.** CORDIS reached
  increment 1 that way and its records carry no organisation at all. The spec
  now requires one record to be opened before a source enters the build order.
