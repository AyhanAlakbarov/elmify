# Shadow-pilot readiness runbook

Phase 1 acceptance (`phased requirements.md` Section 3.5) allows the 5-10
student shadow pilot only after the applicable manually-delivered-service
launch blockers below are cleared, and only after
`uv run python scripts/evaluate_phase1.py` reports a real (non-synthetic)
PASS. **Neither condition is met as of this document.**

Do not mark any blocker cleared without a named, accountable approver and a
dated sign-off. This runbook intentionally ships with every blocker
`status: not started` and `owner: TBD` — no name is invented here.

## Blockers named in the Task 18 brief

| Blocker | Owner | Status | Notes |
|---|---|---|---|
| Legal review of the concierge service terms | TBD | not started | |
| Privacy review (student PII handling, data flows) | TBD | not started | |
| Portal-terms review (target-institution/scholarship portal ToS compliance for manual submission) | TBD | not started | |
| Payment processing arrangement (consultation fee collection) | TBD | not started | Phase 1 software never executes payment; this covers the manual/offline arrangement. |
| Email deliverability / verified sender arrangement | TBD | not started | |
| Agency contract(s) with pilot agencies | TBD | not started | |
| DNS / TLS for the pilot agency domain(s) | TBD | not started | Custom-domain flow: `PENDING_DNS` -> `PENDING_CERTIFICATE` -> `VERIFIED`. |
| Data retention policy sign-off | TBD | not started | `apps/audit` `RetentionPolicy`/`DeletionRequest` machinery exists; the retention *period* and legal basis still need sign-off. |
| DPA (data processing agreement) with each pilot agency | TBD | not started | |

## Additional blockers discovered after Task 18

| Blocker | Owner | Status | Notes |
|---|---|---|---|
| Approved manual program-discovery procedure | TBD | not started | Per the P1-2 amendment of 2026-08-20 (`phased requirements.md` Section 3), Phase 1 satisfies P1-2 through an access-controlled consultant procedure, not automated lead discovery. Phase 1 software provides the retrieval primitives only (`apps/research/discovery.py` `retrieve_official_source`, `egress.py`, `snapshot.py`, `ConsultantResearchTask`); no production caller performs automated channel search. The written procedure — who researches, which feeder channels, how the P1-2 catalog/revalidation/language/aggregator rules are honoured by hand, and how findings enter the catalog — needs authoring and sign-off before the pilot. Automation is deferred to Section 7 (Phase 5). |
| Real benchmark / consultant-review data collection | TBD | not started | `tests/benchmarks/` currently holds only SYNTHETIC placeholder fixtures (see `tests/benchmarks/README.md`). An independent researcher must build 5 blinded reference lists without seeing AI output, and a consultant must review >= 20 diverse profiles with reason codes, before `scripts/evaluate_phase1.py` can be run for a genuine go/no-go decision. |

## Genuine software gap discovered during Task 18 (closed)

| Gap | Owner | Status | Notes |
|---|---|---|---|
| Mandatory MFA for platform admins, agency owners, and counselors (`phased requirements.md` Section 3.4; Task 15's `require_staff_mfa()` sketch) | TBD | closed (independently reviewed 2026-08-16) | `apps.tenancy.middleware.require_staff_mfa()`, enforced by `TenantMembershipMiddleware`, denies owner/counselor/platform-admin requests without a `django-otp` confirmed TOTP device and verified session; students are unaffected. A minimal self-enrollment flow lives at `/mfa/setup/` (`apps/tenancy/views.py`). `tests/tenancy/test_mfa.py::test_*` (per-role deny/allow matrix, self-enrollment end to end, plus a superuser-with-student-membership case) and `tests/acceptance/test_phase1_security.py::test_mandatory_mfa_for_staff_roles_is_enforced` prove enforcement against real django-otp devices/sessions, not a mocked `is_verified()`. A 2026-08-16 security review found and fixed one real gap: the gate keyed off the tenant membership role only, so a Django superuser holding a STUDENT membership skipped MFA and reached `/admin/` — see `docs/security/2026-08-16-tasks-13-18-review.md`. Recovery-code/device-loss flow and rate limiting on the verify step remain unaudited but are not launch-blocking. |

## Additional findings from the 2026-08-16 security review (all closed)

Eight more findings from the same review, unrelated to MFA — cross-tenant
document keys, tenant-context override, a payment double-credit race, a
plaintext-HTTP gap on the evidence bucket, an unrate-limited student-message
endpoint, an unasserted append-only audit trigger, and a stale pre-existing
test failure. All eight are fixed on `master`; none are launch blockers.
Full list, fix commits, and what was deliberately left unchanged (IAM
scope, the still-unwired Task 14/16 HTTP surface): `docs/security/2026-08-16-tasks-13-18-review.md`.

## Sequencing

1. Real independent-researcher and consultant-review data replaces
   `tests/benchmarks/`.
2. `uv run python scripts/evaluate_phase1.py --output docs/validation/phase1-scorecard.md`
   exits `0` (real PASS, not exit `2` synthetic-only).
3. ~~Mandatory MFA is implemented and its acceptance test asserts enforcement
   rather than documenting absence.~~ Done — see the closed gap above.
4. Every blocker in this runbook is cleared with a named owner, a dated
   sign-off, and evidence linked from this table.
5. Only then does the 5-10 student shadow pilot begin. Real admission and
   scholarship outcomes are tracked after the pilot starts and do not block
   this scorecard.

Production customer launch remains additionally blocked by unresolved
legal/commercial items beyond this software-readiness scope, per the parent
plan's review checkpoints.
