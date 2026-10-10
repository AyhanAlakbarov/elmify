# GitHub MCP Direct Surface Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep every GitHub MCP tool callable in normal `codex` and `cco codex` sessions using the full production tool catalog.

**Architecture:** The shared launcher marks the normalized `mcp__github` namespace as direct-only for Codex code mode. The verifier retains its authenticated `get_me` probe but stops replacing the production GitHub catalog with a one-tool allowlist.

**Tech Stack:** Bash, Codex CLI 0.147 configuration overrides, Python `tomllib` in the existing installer validation.

## Global Constraints

- Preserve all GitHub MCP tools; do not add a permanent `enabled_tools` allowlist.
- Keep GitHub optional so an outage cannot prevent Codex from opening.
- Apply the same launcher configuration to `codex` and `cco codex`.
- Keep the existing token handling, CCO mounts, Graphify defaults, validation, backup, and rollback behavior unchanged.
- This workspace is not a Git repository, so no checkpoint commits are possible.

---

### Task 1: Route GitHub through the direct tool surface

**Files:**
- Modify: `test-setup-codex-mcps.sh`
- Modify: `codex-launcher.in`
- Modify: `setup-codex-mcps.sh`
- Modify: `verify-codex-mcps.sh`
- Create: `docs/testing/github-mcp-direct-surface-fix.tdd.md`

**Interfaces:**
- Consumes: the existing `codex`/`cco codex` launcher and GitHub PAT environment injection.
- Produces: one Codex override argument, `features.code_mode.direct_only_tool_namespaces=["mcp__github"]`, on every launcher path.

- [x] **Step 1: Add the failing regression**

Add a fixture Codex stub that prints its received arguments. Add a test that installs and runs the rendered launcher, then requires the direct-only GitHub namespace argument. Update the verifier test to reject any `mcp_servers.github.enabled_tools` override.

```bash
test_github_direct_surface() {
    local case_dir=$sandbox/github-direct-surface home output
    make_fixture "$case_dir"; home=$case_dir/home
    HOME=$home "$case_dir/work/setup-codex-mcps.sh" >/dev/null
    output=$(HOME=$home "$home/.local/bin/codex" mcp list)
    grep -Fxq 'features.code_mode.direct_only_tool_namespaces=["mcp__github"]' <<<"$output"
}
```

- [x] **Step 2: Run the regression and confirm RED**

Run: `./test-setup-codex-mcps.sh github-surface`

Expected: FAIL because the launcher does not yet pass the direct-only namespace override.

- [x] **Step 3: Implement the minimal launcher and migration change**

Add one shared launcher array and pass it through all five Codex execution paths:

```bash
github_config=(-c 'features.code_mode.direct_only_tool_namespaces=["mcp__github"]')
```

Teach the installer to accept the exact currently deployed launcher as a canonical predecessor, then validate that the rendered launcher contains the new argument on every execution path.

- [x] **Step 4: Remove the masking verifier override**

Delete both `-c 'mcp_servers.github.enabled_tools=["get_me"]'` arguments. Keep the real `get_me` invocation and final-message success oracle.

- [x] **Step 5: Run GREEN verification**

Run:

```bash
bash -n codex-launcher.in setup-codex-mcps.sh verify-codex-mcps.sh test-setup-codex-mcps.sh
./test-setup-codex-mcps.sh all
```

Expected: all commands exit zero.

- [x] **Step 6: Record evidence**

Write `docs/testing/github-mcp-direct-surface-fix.tdd.md` with the RED and GREEN commands and results. The final live MCP proof remains the user-run `./apply-cco-mcp-fix.sh`, because installation writes protected home configuration and exercises authenticated network access.
