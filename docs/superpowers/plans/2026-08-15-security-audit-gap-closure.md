# Security Audit Gap Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the two actionable gaps identified in the prior security-audit review (no secret scanning, no pre-commit safety net), and lock in AI/LLM-specific security rules — both in this repo and in the global rule set — so every future AI SaaS project inherits them automatically.

**Architecture:** Two CI/tooling changes in `tehsil_agent` (a blocking gitleaks CI job, a local `pre-commit` config wrapping the project's existing `uv run bandit`/`uv run pip-audit` commands), plus documentation-only additions to the global `~/.config/ai_rules/rules/engineering.md` and the `security-baseline-setup` skill, plus this repo's `CLAUDE.md`. No application code changes — the LLM code (`apps/research/extraction.py`, `apps/funding/explanations.py`) was reviewed during brainstorming and already follows the pattern being codified (untrusted content explicitly labeled as data, schema-constrained output, capped tokens); the new rules exist to keep that pattern from eroding, not to fix a defect.

**Tech Stack:** GitHub Actions, `gitleaks/gitleaks-action@v3`, `pre-commit` (Python, via `uv`), Markdown rule files.

**Spec:** None — this is a bounded change per `superpowers:brainstorming` (extends existing CI/tooling in a repo that already has it); scope was agreed in chat, no separate design doc.

## Global Constraints

- Follow this repo's existing `uv`-based tooling: all Python tool invocations go through `uv run`.
- Third-party GitHub Actions are pinned by version tag, matching this repo's existing convention for `actions/checkout@v4` / `astral-sh/setup-uv@v6` (only the Prowler *Docker* image is digest-pinned, per `security-aws.yml`).
- Do not add a second, independently-versioned copy of Bandit/pip-audit config — pre-commit must call the exact same `uv run bandit -c pyproject.toml -r apps config` / `uv run pip-audit` commands already declared in `CLAUDE.md` and `.github/workflows/ci.yml`, not a separate upstream pre-commit hook repo with its own pinned tool version.
- Global rule edits go in `~/.config/ai_rules/rules/engineering.md` and `~/.agents/skills/security-baseline-setup/SKILL.md` — this is how `tehsil_agent`'s `CLAUDE.md` router already resolves global policy, and how future projects will inherit it via the `security-baseline-setup` skill.

---

### Task 1: Blocking secret-scan CI job (gitleaks)

**Files:**
- Modify: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: a new `secrets` job in `ci.yml`, independent of the existing `test` job — later tasks don't depend on it.

- [x] **Step 1: Confirm the repo is currently clean of secrets**

Run gitleaks against the full repo history via the official Docker image (ad hoc — this image is not committed to the workflow, so it doesn't need digest-pinning):

```bash
docker run -v "$(pwd):/repo" zricethezav/gitleaks:latest git -v /repo
```

Expected: exit code `0`, "no leaks found". If it finds something, stop and handle the finding (rotate/remove the secret) before continuing — do not add a blocking CI check on top of an already-red baseline (this is the documented failure mode in the `security-baseline-setup` skill's Common Mistakes).

- [x] **Step 2: Add the `secrets` job to `ci.yml`**

Add a new top-level job, sibling to the existing `test` job (after the `test:` job block, same indentation level as `test:`):

```yaml
  secrets:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - uses: gitleaks/gitleaks-action@v3
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

`fetch-depth: 0` is required so gitleaks can scan full history, not just the merge commit — the existing `test` job's checkout step is untouched, since it doesn't need history and a full clone would only slow it down. No `GITLEAKS_LICENSE` is needed: this is a personal-account repo, and gitleaks-action only requires a license for organization-owned repos.

- [x] **Step 3: Validate the YAML**

```bash
uv run python -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml'))"
```

Expected: no output, exit code `0` (confirms the new job block didn't break YAML structure — `gitleaks-action` itself can't be run outside GitHub Actions, so this plus the local Docker scan in Step 1 is the available verification).

- [x] **Step 4: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: add blocking gitleaks secret scan"
```

---

### Task 2: Pre-commit hooks for Bandit and pip-audit

**Files:**
- Create: `.pre-commit-config.yaml`
- Modify: `pyproject.toml` (add `pre-commit` to `[dependency-groups].dev`)

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces: `uv run pre-commit` becomes available; local hook IDs `bandit` (stage: `pre-commit`) and `pip-audit` (stage: `pre-push`) — Task 4 references these exact IDs and stages when documenting install instructions.

- [x] **Step 1: Add `pre-commit` as a dev dependency**

```bash
uv add --group dev pre-commit
```

Expected: `pyproject.toml`'s `[dependency-groups].dev` gains a `"pre-commit>=..."` entry and `uv.lock` updates.

- [x] **Step 2: Create `.pre-commit-config.yaml`**

Use **local** hooks that shell out to the project's own pinned `uv run` commands — not the upstream `PyCQA/bandit` or `pypa/pip-audit` pre-commit-hooks repos, which would pull in a second, independently-versioned copy of each tool and drift from `uv.lock`.

```yaml
repos:
  - repo: local
    hooks:
      - id: bandit
        name: bandit (security scan)
        entry: uv run bandit -c pyproject.toml -r apps config
        language: system
        pass_filenames: false
        stages: [pre-commit]
      - id: pip-audit
        name: pip-audit (dependency CVE scan)
        entry: uv run pip-audit
        language: system
        pass_filenames: false
        stages: [pre-push]
```

Bandit runs on every commit (fast, no network). pip-audit runs on push instead of commit — it calls out to the PyPI vulnerability feed over the network, which is too slow/flaky to run on every single commit.

- [x] **Step 3: Install the hooks into this clone's `.git/hooks`**

```bash
uv run pre-commit install --hook-type pre-commit --hook-type pre-push
```

Expected: `pre-commit installed at .git/hooks/pre-commit` and `.git/hooks/pre-push`.

- [x] **Step 4: Run both hooks against the current tree to confirm they pass**

```bash
uv run pre-commit run bandit --all-files
uv run pre-commit run pip-audit --all-files --hook-stage pre-push
```

Expected: both exit `0` (the repo is already clean per the existing CI checks — this just confirms the pre-commit wiring itself works, not that the tools find anything new).

- [x] **Step 5: Commit**

```bash
git add .pre-commit-config.yaml pyproject.toml uv.lock
git commit -m "chore: add pre-commit hooks for bandit and pip-audit"
```

---

### Task 3: Global LLM/AI-feature security rules

**Files:**
- Modify: `~/.config/ai_rules/rules/engineering.md`
- Modify: `~/.agents/skills/security-baseline-setup/SKILL.md`

**Interfaces:**
- Consumes: nothing from Tasks 1–2.
- Produces: a new `## LLM and AI-Feature Security Baseline` section in `engineering.md` and a corresponding row + implementation step in `security-baseline-setup/SKILL.md` — Task 4 references this section by name when updating this repo's `CLAUDE.md`.

This task is documentation-only: no code in this repo enforces these rules (there's no linter for "did you label untrusted content as data"). The point is that the next AI SaaS project — including a future session in *this* repo wiring `extract_claims`/`draft_explanation` into an actual endpoint — reads this before adding an LLM-calling code path.

- [x] **Step 1: Add the new section to `engineering.md`**

Insert after the existing `## Cloud and AWS Security Baseline` section (currently ends before `## Git and Repository Hygiene`):

```markdown
## LLM and AI-Feature Security Baseline

- Any prompt that includes external or untrusted content (scraped pages, user
  input, third-party API responses) must explicitly label that content as
  data, not instructions, in the prompt itself — do not rely on the model's
  instruction-following alone to keep it from being treated as a command.
- Prefer schema-constrained structured output (e.g., a Pydantic model with
  `extra="forbid"`) over free-text parsing for any LLM output a caller acts on
  programmatically.
- Cap `max_output_tokens` (or the provider's equivalent) on every call; an
  uncapped LLM call is a cost bug, not just a correctness one.
- Any endpoint, task, or job that invokes an LLM API must add per-tenant or
  per-user rate limiting in the same change that wires it up — this is the
  actual circuit-breaker against runaway token spend, the LLM-cost analogue
  of the AWS Budget alarm above. A capped-tokens call without a rate limit
  still lets one abusive caller multiply that cost without bound.
- Never log raw prompts or model responses containing user content — see
  `python.md`'s "Never log secrets or unnecessary personal data."
- See the `security-baseline-setup` skill for where this fits alongside the
  Bandit/pip-audit/Prowler baseline.
```

- [x] **Step 2: Verify the section was inserted correctly**

```bash
grep -n "^## " ~/.config/ai_rules/rules/engineering.md
```

Expected: `## LLM and AI-Feature Security Baseline` appears between `## Cloud and AWS Security Baseline` and `## Git and Repository Hygiene`, and the file still has exactly one `## Cloud and AWS Security Baseline` heading (confirms this didn't duplicate or replace it).

- [x] **Step 3: Add a row to the `security-baseline-setup` skill's Quick Reference table**

In `~/.agents/skills/security-baseline-setup/SKILL.md`, in the existing table (the one with `| Layer | Tool | Applies when |` header), add a row after the `IaC misconfiguration | Checkov | ...` row:

```markdown
| LLM prompt-injection / cost abuse | Prompt data-labeling + per-caller rate limiting | Any project with an endpoint or job that calls an LLM API |
```

- [x] **Step 4: Add an implementation step for LLM-backed projects**

In the same file's `## Implementation` section, after the existing `**AWS-provisioning projects:**` block (after its step 6), add:

```markdown
**LLM-backed projects:**

7. Before wiring any new endpoint or job to an LLM API: confirm untrusted
   content in the prompt is labeled as data (not instructions), the output
   is schema-constrained, `max_output_tokens` is capped, and per-tenant/
   per-user rate limiting ships in the same change. See `engineering.md`'s
   LLM and AI-Feature Security Baseline for the full rule.
```

- [x] **Step 5: Verify both edits**

```bash
grep -n "LLM prompt-injection" ~/.agents/skills/security-baseline-setup/SKILL.md
grep -n "LLM-backed projects" ~/.agents/skills/security-baseline-setup/SKILL.md
```

Expected: one match each.

- [x] **Step 6: Commit**

These files live outside the `tehsil_agent` git repo (`~/.config/ai_rules/` and `~/.agents/skills/`) — check whether each is its own git repository before attempting a commit:

```bash
git -C ~/.config/ai_rules status
git -C ~/.agents/skills status
```

If either is a git repository, commit the change there with a message like `"docs: add LLM/AI-feature security baseline rule"`. If neither is a git repository, skip this step — there's nothing to commit to.

---

### Task 4: Document the closed gaps in this repo's `CLAUDE.md`

**Files:**
- Modify: `CLAUDE.md`

**Interfaces:**
- Consumes: the pre-commit hook IDs/stages from Task 2 (`bandit` on `pre-commit`, `pip-audit` on `pre-push`) and the rule section name from Task 3 (`LLM and AI-Feature Security Baseline` in `engineering.md`).
- Produces: nothing further downstream — this is the last task.

- [x] **Step 1: Update the `## Security tooling` section**

Current content (`CLAUDE.md`):

```markdown
# tehsil_agent

## Security tooling

- `uv run bandit -c pyproject.toml -r apps config` — code-level vuln scan (config in `pyproject.toml`'s `[tool.bandit]`)
- `uv run pip-audit` — dependency CVE scan
- Both run in CI (`.github/workflows/ci.yml`) as blocking checks; treat a finding as a real bug to fix or a documented `# nosec <code>` false positive, not something to silence in CI config.
- `.github/workflows/security-aws.yml` (Prowler, AWS account posture) is manual-dispatch only, dormant until `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` exist as repo secrets — enable it once real AWS infra exists for this project.
```

Replace with:

```markdown
# tehsil_agent

## Security tooling

- `uv run bandit -c pyproject.toml -r apps config` — code-level vuln scan (config in `pyproject.toml`'s `[tool.bandit]`)
- `uv run pip-audit` — dependency CVE scan
- Both run in CI (`.github/workflows/ci.yml`) as blocking checks; treat a finding as a real bug to fix or a documented `# nosec <code>` false positive, not something to silence in CI config.
- `.github/workflows/ci.yml` also runs a blocking `gitleaks` secret scan (`secrets` job) on every push/PR.
- Local safety net: `uv run pre-commit install --hook-type pre-commit --hook-type pre-push` runs Bandit on every commit and `pip-audit` on every push, before either reaches GitHub — see `.pre-commit-config.yaml`. Run this once after cloning.
- `.github/workflows/security-aws.yml` (Prowler, AWS account posture) is manual-dispatch only, dormant until `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` exist as repo secrets — enable it once real AWS infra exists for this project.

## LLM/AI security

- `apps/research/extraction.py` and `apps/funding/explanations.py` are the reference pattern for any new LLM-calling code: untrusted content is explicitly labeled as data (not instructions) in the prompt, output is schema-constrained via Pydantic (`extra="forbid"`), and `max_output_tokens` is capped. Follow it, don't weaken it.
- Neither module is wired to a view or task yet. Before wiring one up, add per-tenant/per-user rate limiting in the same change — there is currently no rate limiting anywhere in this app, and an LLM-calling endpoint without it has no cost circuit-breaker. See the global `engineering.md`'s "LLM and AI-Feature Security Baseline" for the full rule.
```

- [x] **Step 2: Verify the diff**

```bash
git diff CLAUDE.md
```

Expected: only the `## Security tooling` section gains the two new bullets, and a new `## LLM/AI security` section is added — nothing else in the file changes.

- [x] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: document gitleaks, pre-commit, and LLM security rules"
```
