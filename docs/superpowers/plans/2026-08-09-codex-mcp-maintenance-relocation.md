# Codex MCP Maintenance Relocation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Relocate the machine-wide Codex MCP maintenance bundle from `tehsil_agent` to `/home/orkhan/.local/share/codex-mcp/` without changing runtime behavior.

**Architecture:** Change the launcher’s Graphify pin to the stable user-data path, retain migration support for the old project path, and use one transactional host script to install and verify the bundle. Project copies are deleted only after both production launch paths pass.

**Tech Stack:** Bash, Python standard library, Codex CLI, CCO.

## Global Constraints

- Do not read, copy, print, or modify the GitHub token.
- Preserve `/home/orkhan/.codex/config.toml`, `/home/orkhan/.bashrc`, and `/home/orkhan/.local/bin/codex` on any failed migration.
- Keep Perplexity disabled.
- Keep `graphify-out/graph.json` non-empty and pinned through an absolute user-data path.
- This workspace has no usable Git repository; do not create commits.

---

### Task 1: Specify the Graphify path migration

**Files:**
- Modify: `test-setup-codex-mcps.sh`

**Interfaces:**
- Consumes: the rendered launcher produced by `setup-codex-mcps.sh`.
- Produces: `test_graph_location_migration()` and the `graph-location` test selector.

- [x] **Step 1: Add the failing migration test**

Create a fixture whose installed launcher contains:

```bash
graph_path="$home/Desktop/tehsil_agent/graphify-out/graph.json"
```

Run setup and require the rendered launcher to contain:

```bash
graph_path="$home/.local/share/codex-mcp/graphify-out/graph.json"
```

- [x] **Step 2: Run the test and verify RED**

Run: `./test-setup-codex-mcps.sh graph-location`

Expected: non-zero because the template still uses the project path.

### Task 2: Implement the stable bundle path

**Files:**
- Modify: `codex-launcher.in`
- Modify: `setup-codex-mcps.sh`
- Modify: `test-setup-codex-mcps.sh`

**Interfaces:**
- Consumes: `__TARGET_HOME__` rendered as the user home.
- Produces: a launcher pinned to `$home/.local/share/codex-mcp/graphify-out/graph.json` while accepting old launchers during migration.

- [x] **Step 1: Change the launcher template path**

Use:

```bash
graph_path="$home/.local/share/codex-mcp/graphify-out/graph.json"
```

- [x] **Step 2: Normalize the former project path during preflight validation**

Before comparing an existing launcher with supported variants, replace the former Graphify path with the new path in memory. Do not mutate the live launcher during preflight.

- [x] **Step 3: Update existing assertions and migration fixtures**

All post-install assertions must require the stable user-data path; the new migration fixture remains the only intentional old-path input.

- [x] **Step 4: Run GREEN and regression tests**

Run:

```bash
./test-setup-codex-mcps.sh graph-location
./test-setup-codex-mcps.sh all
bash -n setup-codex-mcps.sh verify-codex-mcps.sh test-setup-codex-mcps.sh codex-launcher.in
```

Expected: every command exits `0`.

### Task 3: Build the transactional host migration

**Files:**
- Create: `relocate-codex-mcp-maintenance.sh`

**Interfaces:**
- Consumes: the four maintenance files and `graphify-out/graph.json` from `tehsil_agent`.
- Produces: `/home/orkhan/.local/share/codex-mcp/`, an updated live launcher, a recovery backup, and a clean project root.

- [x] **Step 1: Validate and stage a candidate bundle**

Copy only the approved five assets into a temporary directory under `/home/orkhan/.local/share`, set executable modes, run shell syntax checks, and run `test-setup-codex-mcps.sh all` from the candidate.

- [x] **Step 2: Back up live state and install the candidate**

Create a unique directory under `/home/orkhan/.codex/backups/` containing the current config, Bash configuration, launcher, and any prior destination bundle.

- [x] **Step 3: Run setup and production verification**

Run:

```bash
/home/orkhan/.local/share/codex-mcp/setup-codex-mcps.sh
/home/orkhan/.local/share/codex-mcp/verify-codex-mcps.sh
```

Expected final line: `ALL MCP LAUNCH CHECKS PASSED`.

- [x] **Step 4: Roll back on any failure**

Restore the backed-up config, Bash configuration, launcher, and prior bundle. Retain the failed candidate inside the backup for diagnosis.

- [x] **Step 5: Delete project copies only after success**

Remove the three scripts, launcher template, `graphify-out/`, and the one-time relocation script from `tehsil_agent`.

### Task 4: Verify the completed separation

**Files:**
- Verify: `/home/orkhan/.local/share/codex-mcp/`
- Verify: `/home/orkhan/Desktop/tehsil_agent/`

**Interfaces:**
- Consumes: installed host state.
- Produces: final evidence that the runtime bundle is independent from the project.

- [x] **Step 1: Verify the destination bundle and live launcher**

Require all five assets, a non-empty 70-node graph, and the stable Graphify path in `/home/orkhan/.local/bin/codex`.

- [x] **Step 2: Verify project cleanup**

Require the relocated files and `graphify-out/` to be absent from `tehsil_agent` while `idea.md`, project dependencies, docs, and skill observations remain.

- [x] **Step 3: Report the backup path and verification result**

Report exactly what moved, what was removed, and how to run the permanent verifier from its new path.
