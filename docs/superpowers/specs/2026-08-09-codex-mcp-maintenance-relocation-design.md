# Codex MCP Maintenance Relocation Design

## Goal

Remove machine-wide Codex MCP maintenance assets from `tehsil_agent` without changing either `codex` or `cco codex` behavior.

## Layout

Move the self-contained bundle to `/home/orkhan/.local/share/codex-mcp/`:

- `setup-codex-mcps.sh`
- `verify-codex-mcps.sh`
- `test-setup-codex-mcps.sh`
- `codex-launcher.in`
- `graphify-out/graph.json`

Keep the installed launcher at `/home/orkhan/.local/bin/codex` and Codex configuration at `/home/orkhan/.codex/config.toml`.

## Migration

Create and validate a candidate bundle, back up any existing destination, install the candidate, and run its setup and full verifier. Update the launcher template so Graphify uses the new absolute graph path. Delete the project copies only after both Codex launch paths pass authenticated GitHub and Graphify checks.

## Failure Handling

Before successful verification, retain every project source. If setup or verification fails, restore the prior destination and live Codex files through the existing setup rollback, leaving `tehsil_agent` usable.

## Testing

- Regression tests must fail while the old project Graphify path remains.
- Installer tests and shell syntax must pass after relocation.
- The host verifier must pass configuration, authenticated GitHub, and Graphify invocation for both `codex` and `cco codex`.
- After success, no relocated maintenance asset may remain in `tehsil_agent`.
