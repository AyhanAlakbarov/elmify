# CCO MCP Runtime Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the uv-installed Python MCP servers callable inside `cco codex` and make the GitHub verifier incapable of matching its own prompt.

**Architecture:** Add one read-only shared uv-runtime mount to the existing launcher. Permit only the immediately previous rendered launcher as an installer migration source, retain validated-candidate installation, and verify GitHub from Codex's final-message file instead of the full event log.

**Tech Stack:** Bash, Python 3 standard library, Codex CLI, cco native bubblewrap sandbox.

## Global Constraints

- Keep the native `cco` sandbox enabled.
- Mount `~/.local/share/uv/python` read-only.
- Do not make GitHub required unless a corrected real tool-call test still fails after startup.
- Do not expose or print the GitHub token.
- This directory is not a Git repository; skip commit steps.

---

### Task 1: Mount the uv runtime and correct verification

**Files:**
- Modify: `test-setup-codex-mcps.sh`
- Modify: `codex-launcher.in`
- Modify: `setup-codex-mcps.sh`
- Modify: `verify-codex-mcps.sh`

**Interfaces:**
- Consumes: the existing rendered launcher template and validated-candidate installer flow.
- Produces: a mode-0700 launcher containing `--add-dir "$home/.local/share/uv/python:ro"` and a verifier that checks an exact final response.

- [x] **Step 1: Add the failing launcher regression assertion**

Add to `assert_installed()` in `test-setup-codex-mcps.sh`:

```bash
grep -Fq -- '--add-dir "$home/.local/share/uv/python:ro"' "$home/.local/bin/codex"
```

Add a migration fixture that renders the new template, removes only the uv-runtime mount to represent the immediately previous known launcher, runs the installer, and asserts the mount is restored.

- [x] **Step 2: Run the regression test and verify RED**

Run:

```bash
./test-setup-codex-mcps.sh idempotent
```

Expected: nonzero exit because the installed launcher lacks the uv-runtime mount.

- [x] **Step 3: Add the minimal runtime mount**

In the `args=(...)` array in `codex-launcher.in`, add exactly:

```bash
--add-dir "$home/.local/share/uv/python:ro"
```

Keep all existing mounts and their modes unchanged.

- [x] **Step 4: Permit only the previous known launcher migration**

In the installer preflight, render the current expected launcher and derive the sole accepted previous form by removing this exact fragment once:

```python
'--add-dir "$home/.local/share/uv/python:ro"'
```

Accept an existing launcher only when its bytes equal the current rendered launcher or that derived previous form. Candidate and post-install validation must continue requiring exact current-template bytes.

- [x] **Step 5: Remove the verifier false positive**

Create temporary verification files under the mounted workspace, pass `--output-last-message` separately to normal and `--cco` Codex executions, and require exact output:

```bash
grep -Fxq 'GITHUB_MCP_OK' "$last_message_file"
```

Do not search the combined log containing the prompt.

- [x] **Step 6: Run automated checks and verify GREEN**

Run:

```bash
bash -n setup-codex-mcps.sh codex-launcher.in verify-codex-mcps.sh test-setup-codex-mcps.sh
./test-setup-codex-mcps.sh all
```

Expected: exit 0 with no assertion or syntax failures.

- [ ] **Step 7: Reproduce the sandbox boundary**

Run the PDF MCP under `cco` once without the uv runtime mount and once with it. Expected results:

```text
without mount: exit 1, execvp ... No such file or directory
with mount: timeout exit 124, proving the MCP process remained running
```

- [ ] **Step 8: Install and run a fresh user verification**

The user runs:

```bash
cd /home/orkhan/Desktop/tehsil_agent && ./setup-codex-mcps.sh && ./verify-codex-mcps.sh
```

Then a fresh `cco codex` session must make real calls to `github.get_me`, `graphify.graph_stats`, `headroom.headroom_stats`, and `opendataloader_pdf.convert_pdf`. Keep GitHub optional if the corrected call passes.
