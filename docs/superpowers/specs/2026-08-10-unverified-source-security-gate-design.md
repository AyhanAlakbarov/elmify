# Unverified-Source Security Gate Design

**Date:** 2026-08-10
**Status:** Approved (2026-08-10)

## Goal

Prevent installation or update of plugins, packages, skills, MCP servers, and agent tools from custom or otherwise unverified sources until the exact artifact has been security-reviewed and the user explicitly approves it.

## Trust classification

- **Confirmed source:** an official package registry or distributor, or a repository/release controlled by the project's verified official maintainer.
- **Unverified source:** a custom repository, fork, mirror, gist, direct archive, unknown maintainer, or source whose ownership cannot be verified.
- Ambiguous ownership is unverified by default.

Confirmed sources remain subject to normal pinning, compatibility, and integrity checks, but do not trigger this additional review-and-approval gate.

## Shared-rule changes

Update the existing shared policy instead of adding a new skill or duplicating rules across installers:

1. `rules/engineering.md` covers packages, dependencies, installers, scripts, and developer tools.
2. `rules/artifacts.md` covers plugins, skills, MCP servers, and other agent tooling.

Both rules will require the same unverified-source workflow:

1. Resolve and pin the exact commit, tag, release, or artifact digest.
2. Verify source ownership; uncertainty keeps the source unverified.
3. Inspect provenance, contents, dependencies, installers, hooks, instruction-file writes, permissions, network behavior, subprocess behavior, and published vulnerability evidence.
4. Report findings, limitations, and a recommendation.
5. Wait for explicit user approval of that exact reviewed artifact.
6. Install without automatic updates when supported, then run a scoped smoke test.

Any artifact change invalidates the prior approval and requires a new review.

## Verification

Use three reusable instruction-contract scenarios:

1. A custom GitHub repository must be reviewed and explicitly approved before installation.
2. A verified official-maintainer repository does not trigger the additional gate.
3. A repository with ambiguous ownership is treated as unverified and blocked pending review and approval.

Also verify that both shared rule files contain the same trust classification and that unrelated rules remain unchanged.

## Non-goals

- No new dependency, scanner, installer abstraction, or dedicated skill.
- No claim that official sources are vulnerability-free.
- No automatic installation, update, or network access as part of this policy change.
