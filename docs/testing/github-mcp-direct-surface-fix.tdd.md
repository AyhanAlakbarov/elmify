# GitHub MCP Direct Surface Fix — TDD Evidence

## Source

- Design: [`../superpowers/specs/2026-08-09-cco-mcp-runtime-fix-design.md`](../superpowers/specs/2026-08-09-cco-mcp-runtime-fix-design.md)
- Plan: [`../superpowers/plans/2026-08-09-github-mcp-direct-surface-fix.md`](../superpowers/plans/2026-08-09-github-mcp-direct-surface-fix.md)

## User journey

As a user launching either `codex` or `cco codex`, I want the complete authenticated GitHub MCP catalog to remain callable so a focused verifier cannot hide a production tool-registration failure.

## RED evidence

- `./test-setup-codex-mcps.sh github-surface` exited `1` before the launcher supplied the direct-only namespace.
- The first verifier assertion used a negated command whose failure was exempt from Bash `errexit`; it was corrected to an explicit conditional return. `./test-setup-codex-mcps.sh verifier` then exited `1` while the production verifier still contained `mcp_servers.github.enabled_tools=["get_me"]`.

## GREEN evidence

| Guarantee | Command | Type | Result |
|---|---|---|---|
| Rendered launchers pass `features.code_mode.direct_only_tool_namespaces=["mcp__github"]` | `./test-setup-codex-mcps.sh github-surface` | Integration | PASS, exit `0` |
| The GitHub verifier no longer narrows the production tool catalog | `./test-setup-codex-mcps.sh verifier` | Regression | PASS, exit `0` |
| Syntax, idempotence, every supported migration, rollback, and all existing regressions remain valid | `bash -n ... && ./test-setup-codex-mcps.sh all` | Integration | PASS, exit `0` |
| Codex 0.147 accepts the direct-only configuration key and namespace value under strict parsing | temporary `codex app-server --strict-config --listen off` probe | Compatibility | PASS; parser reached the expected no-transport boundary |

## Coverage and remaining live check

The project is a Bash installer without a coverage harness; every defined installer regression ran through `./test-setup-codex-mcps.sh all`. `shellcheck` is not installed. The remaining proof is the authenticated live installation and MCP invocation through `./apply-cco-mcp-fix.sh`, which must run in the user's terminal because it writes protected home configuration and uses the protected GitHub token.
