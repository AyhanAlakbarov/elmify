# elmify

<!-- Merge conflict here? Area guidance moved to .claude/rules/ on 2026-10-14 (PR #206). Put your
hunk in the matching rules file (index at the bottom) and keep this file as it is on master; never
take a pre-split side. tests/test_instruction_files.py fails if the old text comes back. -->

## Commands (the CI gates, `.github/workflows/ci.yml`)

- Install: `uv sync --locked --group dev`. Postgres: `docker compose up -d postgres`.
- Lint: `uv run ruff check .` — lint only, never `ruff format` (the tree is not formatter-clean; it rewrites hundreds of untouched files).
- Types: `uv run mypy apps config`
- Tests: `uv run pytest -q`. Each checkout gets its own test DB (`config/settings/database.py`);
  set `POSTGRES_DB` to choose one. `live` tests are skipped by default; `-m live` runs them.
  Sandboxed agent sessions can't reach docker Postgres: run `pixi install` once per worktree and
  pytest starts its own Postgres 17.10 (`tests/ephemeral_pg.py`; `ELMIFY_EPHEMERAL_PG=0` opts out).
- Django: `uv run python manage.py check` and `uv run python manage.py makemigrations --check --dry-run`
- Templates: `uv run cfn-lint`. OCR (its own Python 3.12 project): `UV_PYTHON=3.12 uv sync --project ocr --frozen`
  then `uv run --project ocr pytest ocr -q`. CI also builds the web, OCR and portal images and
  typechecks/builds `extension/` (`npm`), with its `-m extension` pytest job.
- Never hand-edit `uv.lock` or an applied migration; never push to `master` — branch and open a PR.

## Frontend and design

No stack, template system, or design-authority skill is pinned here. The presentation layer (which
UI stack, which skills arbitrate design decisions, animation approach, form-rendering conventions) is
decided fresh from the idea by the frontend/orchestrator skill in use (`spec-to-site-orchestrator`)
at build time — not prewritten in this file or in `phased requirements.md`.

## Tenant branding

- White-label rule: tenant `brand_primary_color` is the only tenant-variable color. `apps/tenancy/services.py::validate_brand_contrast` (WCAG AA) and `validate_brand_palette` (also checks the derived `--brand-tint` mix, see that file's own comments for the derivation math) are the source of truth — this logic is stack-independent and survives whatever presentation layer is chosen.

## Security tooling

- `uv run bandit -c pyproject.toml -r apps config ocr/read_pages.py` — code-level vuln scan (config in `pyproject.toml`'s `[tool.bandit]`)
- `uv run pip-audit --ignore-vuln PYSEC-2026-2034 --ignore-vuln PYSEC-2026-3412` — dependency CVE
  scan, plus a second pass over the OCR program's own lock (`ocr/uv.lock`). Both suppressions are
  assessed in `ci.yml`'s comment and must match `.pre-commit-config.yaml`
- Both run in CI (`.github/workflows/ci.yml`) as blocking checks; treat a finding as a real bug to fix or a documented `# nosec <code>` false positive, not something to silence in CI config.
- `.github/workflows/ci.yml` also runs a blocking `gitleaks` secret scan (`secrets` job) on every push/PR. `gitleaks-action` is free for personal-account repos; if this repo moves to an organization, add a `GITLEAKS_LICENSE` repo secret or the job fails.
- Local safety net: `uv run pre-commit install --hook-type pre-commit --hook-type pre-push` runs Bandit on every commit and `pip-audit` on every push, before either reaches GitHub — see `.pre-commit-config.yaml`. Run this once after cloning.
- `.github/workflows/security-aws.yml` (Prowler, AWS account posture) is manual-dispatch only, dormant until an OIDC-assumable read-only IAM role exists (its ARN as the `AWS_PROWLER_ROLE_ARN`
  secret, the region as the `AWS_REGION` variable; no static keys) — enable it once real AWS infra exists for this project.
- AI code review on PRs comes from Claude Code via `.github/workflows/claude-code-review.yml` (automatic on every PR) and `claude.yml` (on an `@claude` mention), authenticated by the `CLAUDE_CODE_OAUTH_TOKEN` repo secret. CodeRabbit was removed 2026-09-14 so PRs get one AI review, not two. A PR that edits either workflow file gets no review: the action refuses to run a workflow that differs from the default branch's copy, logs a warning, and still reports success.

## Python version: five declarations, one number

`requires-python`, ruff's `target-version`, mypy's `python_version`, `ci.yml`'s
`python-version` and the `Dockerfile`'s `FROM python:` must all name the same major.minor.
`tests/test_bootstrap.py::test_every_declared_python_version_agrees` enforces it.

This is not tidiness. `uv sync` builds the venv against `requires-python`, so when a
base-image bump moved the image to 3.14 while the pin stayed 3.12, the container got
`.venv/lib/python3.12` under a 3.14 interpreter and **could not import Django at all** —
web, worker, portal and migration alike (the browser stage it also broke is since deleted). Nothing failed: the test suite runs on
the host's interpreter, and until the `portal-sandbox` job existed CI never built an
image, so a dead container passed every check. Dependabot's docker updater reads `FROM`
lines and knows nothing about `requires-python`; it will propose the bump again, and the
test is what turns that from a silent break into a loud one.

Changing Python is therefore a five-file change plus a re-lock, never a base-image bump.

## Static files: tests cannot see a production-only failure

`config/settings/test.py` swaps in `StaticFilesStorage`; production (`base.py`) uses
`CompressedManifestStaticFilesStorage`, which raises on any `{% static %}` path missing from the
manifest. When a change adds templates or static references, run `collectstatic` under production
settings — the `Dockerfile` and CI (`ci.yml`) both run it now, so a missing path fails the build.

## Area rules (`.claude/rules/`)

Each file loads by itself when Claude reads a file matching its `paths:`. Its sections keep
their old headings, so a code comment citing `CLAUDE.md, "<section>"` means the heading of
that name in the file listed here. Designing or writing a spec in one of these areas without
opening its code? Read the file first; nothing loads it for you then.

- `.claude/rules/row-level-security.md`: "Row-level security: what actually filters a query"
- `.claude/rules/migrations.md`: "Migrations: squash once, in the one window where it is cheap"
- `.claude/rules/web-fetching.md`: "Web fetching"
- `.claude/rules/institution-safety-screen.md`: "The institution-safety screen was removed — 2026-09-14, and this is the record"
- `.claude/rules/portals.md`: "The portal browser: its security model is the sandbox"; "Application automation (Phase 3) — decided in advance, and now partly built"
- `.claude/rules/cv-and-letters.md`: "Who reads a CV warning — the student, not a counsellor"; "One ledger, every consumer"; "The CV-requirement corpus — read this before measuring discovery or derivation"; "The rule catalogs — read these before researching CV or letter conventions"
- `.claude/rules/llm-ai-security.md`: "LLM/AI security"
- `.claude/rules/derived-data-and-erasure.md`: "Derived data and the ML corpus — deliberately incomplete"; "Erasure: the schedule is deferred, and that is a deployment blocker"
- `.claude/rules/research-map.md`: "Research area map: where the search engine lives"
- `.claude/rules/funding-map.md`: "Funding area map: the catalogue and a student's pack"
- `.claude/rules/research-wiki.md`: "Research wiki: answer funding and discovery questions from docs/wiki/"

The two map files say where code lives, not how to write it. Briefing a subagent (Explore included) on
research or funding code? Name the map in the brief and tell it to read the map first: subagents do not
see this file, and a map loads by itself only when a file under its `paths:` is read on its own.

A question about funding, schemes, countries, institutions or discovery sources starts at `docs/wiki/index.md`, not the research folder.
