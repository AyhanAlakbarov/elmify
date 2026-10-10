# Docker Build-Context Security Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Prevent local credentials, repository metadata, generated data, and agent artifacts from entering the worker-image build context.

**Architecture:** Add one root `.dockerignore` denylist and leave the existing `Dockerfile` unchanged. Use a failing file-existence check, exact-pattern checks, and the existing local AWS-harness suite; defer Docker's behavioral build check until a container engine is separately approved and installed.

**Tech Stack:** Docker ignore syntax, POSIX shell checks, Git, pytest through `uv`.

## Global Constraints

- Create only the root `.dockerignore` implementation file.
- Do not modify `Dockerfile` or application source.
- Do not install a container engine, build or push an image, create ECR, or deploy CloudFormation.
- Apply the approved configuration-only TDD exception: do not add a synthetic unit test for Docker's ignore parser.
- Keep application source, migrations, scripts, templates, static assets, `pyproject.toml`, and `uv.lock` available to the build context.

---

### Task 1: Exclude Sensitive and Local-Only Build Inputs

**Files:**
- Create: `.dockerignore`
- Verify: `Dockerfile`
- Verify: `tests/research/test_controlled_egress_validation.py`
- Verify: `tests/research/test_fairness_validation.py`
- Verify: `tests/integration/test_controlled_egress.py`
- Verify: `tests/integration/test_sqs_fair_queue.py`

**Interfaces:**
- Consumes: the repository root as the build context used by `Dockerfile`'s `COPY . .` instruction.
- Produces: native Docker exclusions for credentials, local data, caches, VCS metadata, and agent artifacts.

- [x] **Step 1: Record the failing baseline**

Run:

```bash
test -f .dockerignore
```

Expected: exit status `1` because `.dockerignore` does not exist.

- [x] **Step 2: Add the minimal native exclusion file**

Create `.dockerignore` with exactly:

```dockerignore
.git*
.env*
.aws
*.pem
*.key

.venv
**/__pycache__
**/*.py[cod]
.pytest_cache
.mypy_cache
.ruff_cache
.coverage
htmlcov
coverage.xml
*.log

*.sqlite3
media

graphify-out
.superpowers
skill-observations
skill-updates
```

- [x] **Step 3: Verify every security boundary is represented**

Run:

```bash
while IFS= read -r pattern; do
  [ -z "$pattern" ] || rg -Fx -- "$pattern" .dockerignore >/dev/null || exit 1
done <<'EOF'
.git*
.env*
.aws
*.pem
*.key
.venv
**/__pycache__
**/*.py[cod]
.pytest_cache
.mypy_cache
.ruff_cache
.coverage
htmlcov
coverage.xml
*.log
*.sqlite3
media
graphify-out
.superpowers
skill-observations
skill-updates
EOF
```

Expected: exit status `0` with no output.

- [x] **Step 4: Verify required runtime inputs remain present**

Run:

```bash
for path in Dockerfile pyproject.toml uv.lock apps config scripts; do
  test -e "$path" || exit 1
done
```

Expected: exit status `0` with no output.

- [x] **Step 5: Run the focused no-AWS regression suite**

Run:

```bash
env -u PHASE1_VALIDATION_STACK -u PHASE1_VALIDATION_QUEUE_URL \
  UV_CACHE_DIR=/tmp/tehsil-agent-uv-cache \
  uv run pytest \
  tests/research/test_controlled_egress_validation.py \
  tests/research/test_fairness_validation.py \
  tests/integration/test_controlled_egress.py \
  tests/integration/test_sqs_fair_queue.py -q
```

Expected: `45 passed, 2 skipped`; both skips occur before any AWS client call because the live environment gates are absent.

- [x] **Step 6: Check and commit only the implementation file**

Run:

```bash
git diff --check -- .dockerignore
git add .dockerignore
git commit -m "build: secure Docker build context"
```

Expected: the diff check produces no output and the commit contains only `.dockerignore`.
