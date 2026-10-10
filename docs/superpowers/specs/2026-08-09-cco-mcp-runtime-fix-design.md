# CCO MCP Runtime Fix

## Goal

Make every enabled MCP callable from `cco codex`, without weakening the native sandbox or making a transient GitHub outage prevent Codex from opening.

## Confirmed cause

`graphify`, `headroom`, and `opendataloader_pdf` are uv-installed Python programs. Their launchers are mounted inside `cco`, but their shebangs resolve into `~/.local/share/uv/python`, which is not mounted. The sandbox therefore reports `No such file or directory`. Mounting that shared runtime lets the server start.

GitHub is separate: the catalog is cached, and its tools may be absent from the first model turn when optional MCP startup is interrupted. The existing verifier also produced a false positive because it searched a log containing its own expected phrase.

The remaining GitHub failure is a tool-surface mismatch, not authentication. `gpt-5.6-sol` is code-mode-only, GitHub exposes a large MCP namespace, and the focused verifier masked the production behavior by reducing that namespace to `get_me`. A normal `cco codex` session therefore initialized and authenticated GitHub while `tools.mcp__github__get_me` was absent from the code-mode callable registry.

## Design

1. Add the single read-only mount `~/.local/share/uv/python:ro` to the existing `cco` launcher.
2. Allow the installer to migrate only the immediately previous known launcher form, then install the newly rendered launcher through its existing validated-candidate and rollback path.
3. Change verification to inspect only Codex's final-message file, not the complete log containing the prompt.
4. Keep GitHub optional. First verify it with a real `get_me` call after startup; do not set `required = true` unless the corrected test still reproduces a timing failure.
5. Configure `mcp__github` as a direct-only code-mode namespace in the common launcher. Preserve the full GitHub MCP catalog; do not add a permanent tool allowlist.
6. Remove the verifier's temporary `enabled_tools=["get_me"]` override so its GitHub call exercises the deployed production surface in both `codex` and `cco codex`.

## Verification

- Regression test fails before the mount exists and passes afterward.
- Direct `cco` boundary test: Python MCP fails without the runtime mount and stays running with it.
- Installer fixture passes migration, idempotence, rollback, and syntax checks.
- User-run smoke test confirms callable tools from GitHub, graphify, headroom, and opendataloader_pdf in a fresh `cco codex` session.
- The focused GitHub probe succeeds without narrowing the server's enabled tools, proving full-surface registration rather than only authentication.

## Safety

The new mount is read-only and limited to uv-managed Python runtimes. Direct-only routing changes where Codex invokes GitHub tools, not which tools or credentials are available. No credential handling, MCP permissions, or repository files are broadened.
