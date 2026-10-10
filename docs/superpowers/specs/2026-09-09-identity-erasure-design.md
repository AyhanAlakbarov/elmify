# Erasure of login identity

Status: design, awaiting review. Completes `apps/audit/redaction.py`, which erases everything a
student's `Membership` reaches but cannot reach the login itself.

Supersedes the "Does not anonymise the `User`" carve-out in
`docs/superpowers/specs/2026-09-08-erasure-by-redaction-design.md`.

## The gap

`advance_deletion` now redacts 124 fields across 32 models and writes `EXECUTED`. The person is
still identifiable, because **`auth.User` survives untouched**: `email` (the login address),
`first_name`, `last_name`, `username`, and a working password hash.

The graph walk cannot see it, and this is structural rather than an oversight.
`student_reachable_models()` grows the set by adding models whose foreign keys point *into* it.
`Membership.user` points the other way — out, at `auth.User` — so no walk seeded at `Membership`
will ever reach it. Adding it to the classification map is not the fix; see "Why not the map".

Also outside the walk and also identity: **`otp_totp.TOTPDevice`**, which holds the TOTP secret in
`key`. A working second factor surviving an erasure is the same failure class as the portal
credentials `delete_student_portal_credentials` already destroys.

Not reachable in production today: `advance_deletion` still has no caller. That is what makes this
fixable before it matters, and it is why this ships **before** the operator console that gives it
one. An erasure surface over an engine that leaves the login intact would record a false claim on
its first real use.

## What "best" means here

Ranked. The first two are binding; the rest break ties. Criteria 1, 3, 6, 7 are inherited from the
erasure-by-redaction design; 2, 4, 5 and 8 are specific to touching shared authentication.

1. **Legally true, not aspirational.** After `EXECUTED`, nothing surviving can single out the
   person — or the record says plainly that something does.
2. **Never irreversibly breaks an innocent third party's account.** `auth.User` is shared across
   roles and tenants and the scrub cannot be undone. Locking out a counselor, a platform admin, or
   another agency's student is unrecoverable in a way a missed field is not.
3. **Fails closed.** Refuse rather than half-do, and never record a completion that did not happen.
4. **Enforced by a test, not by prose.** The completeness test structurally cannot cover
   `auth.User`, so this change has zero inherited coverage. Something must fail when a future
   field on `auth.User` holds identity.
5. **Reversible while it still can be.** Ordering that leaves retryable state rather than a
   half-erased person.
6. **Reuses existing seams.**
7. **Weakens no existing invariant.**
8. **Smallest thing that is true.**

**Criteria 1 and 2 conflict, and 2 wins.** When the person holds another active membership, the
login must keep working, so identity survives and that erasure is *incomplete*. The design records
that fact rather than hiding it (see "When the guard blocks"). **This ranking is the one judgement
call in this document.** Inverting it means erasing a student can lock a counselor out of their
account permanently, with no undo. That was judged worse than a recorded, lawful partial erasure.

## Why deletion is not available

Same shape as the parent design, for a different reason, and measured rather than assumed:

- `Membership.user` is `CASCADE`, so deleting a `User` deletes their memberships **at every
  agency**.
- `Membership` is then `PROTECT`ed by 30 models, so the delete raises `ProtectedError` anyway.

So identity is redacted in place, exactly like everything else. No new mechanism.

`otp_totp.TOTPDevice` is the exception: it is `CASCADE` from `User` with nothing protecting it, it
is a credential rather than a record, and nothing needs it after erasure. It is **deleted**, not
redacted.

## Why not the classification map

Three placements were considered. The map and `redact_student` were both rejected.

- **Adding `auth.User` to `REDACT`.** The map's contract is that a REDACT field is *always*
  overwritten, which is what makes the completeness test meaningful. This scrub is conditional on a
  membership count. A conditional class corrupts the one guarantee the map provides.
- **Doing it inside `redact_student`.** That function is tenant-scoped and now *guards* on the
  ambient tenant matching its argument. `auth.User` is global. Mixing a cross-tenant write into it
  breaks its own stated invariant.
- **A separate `redact_identity(user)`** — chosen. Different scope (global, not tenant), different
  trigger (conditional), different data (credentials, not records), its own tests.

## The design

`apps/audit/identity.py`, a sibling of `redaction.py`. Called from `advance_deletion` inside the
existing `transaction.atomic()`, **after** `redact_student` returns.

### First, the erasure deactivates the membership

Found while reviewing this spec, and it is not cosmetic. `Membership.active` is classified KEEP, so
today it stays `True` through an erasure. Two consequences:

- **Access is not revoked.** `apps/tenancy/middleware.py:64` resolves a request's tenant with
  `Membership.objects.filter(user_id=request.user.id, active=True).first()`. In the case below where
  the login legitimately survives, the erased person can still sign in and reach the dashboard of
  the agency that just erased them. Their data is redacted; their access is not.
- **It poisons the guard.** A tombstone membership left `active` counts as a live relationship
  forever, so a later erasure elsewhere would refuse to scrub identity on the strength of a
  relationship that has already ended.

So `advance_deletion` sets `request.student.active = False` on the `EXECUTED` path, after
`redact_student` and before the identity scrub. This is a state transition, not redaction — it
records that the relationship ended, and `active` stays KEEP because it carries no personal data.

### The guard

With the membership already deactivated, the guard asks "does any active membership remain?" — and
answering that requires reading across tenants, which is the hardest part of this design.

**The obvious form is wrong, and it was shipped before being caught.** This:

```python
Membership._base_manager.filter(user_id=user_id, active=True).exists()   # WRONG
```

drops Django's `TenantManager` filter but not Postgres's row-level policy. `tenancy_membership` is
`ENABLE` + `FORCE ROW LEVEL SECURITY` with `USING (tenant_id = current_setting('app.tenant_id'))`
(`apps/tenancy/migrations/0002_rls.py`), the production runtime role is `NOBYPASSRLS`
(`scripts/create_runtime_role.sql`), and `advance_deletion` sets that GUC to the *erasing* tenant on
the same connection before the guard runs. So in production it sees only the erasing agency, finds
nothing, and scrubs the login of a person still active elsewhere — criterion 1 defeating criterion 2,
which this document ranks the other way.

No test caught it because the test database role bypasses RLS. Dumping the SQL Django generates does
not catch it either: the predicate is applied by Postgres, not written by Django.

### Measured, 2026-09-09 — four options, on a real NOBYPASSRLS role

A minimal repro with the same policy shape, `FORCE ROW LEVEL SECURITY`, `app.tenant_id` set to the
erasing tenant A, and one user holding an active membership in tenant B:

| Option | Sees B's row? | Exposes beyond one boolean |
|---|---|---|
| `_base_manager`, plain SELECT (the wrong form above) | **No** | — |
| `SECURITY DEFINER` function owned by the **table owner** | **No** | — |
| `SECURITY DEFINER` function owned by a **`BYPASSRLS`** role | **Yes** | **nothing** |
| An extra permissive `POLICY` on the table | Yes | every membership row, both tenants |
| A separate `BYPASSRLS` role for the connection | Yes | every membership row, both tenants |

**The second row is the trap.** `FORCE ROW LEVEL SECURITY` applies policies to the table owner too,
so a definer function owned by the ordinary owner is filtered exactly like ordinary code. It looks
like a fix, changes nothing, and passes every test — the original bug one layer down. Do not reach
for it.

### Decision: a `SECURITY DEFINER` function owned by a `BYPASSRLS` role

It is the only option that answers the question without widening what is readable. The other two
working options dissolve tenant isolation on `tenancy_membership` — the table the whole multi-tenant
model rests on — to answer one yes/no question.

Three conditions, none optional:

1. **Pin `search_path` on the function** (`SET search_path = pg_catalog, public`). An unpinned
   `SECURITY DEFINER` function is a textbook privilege-escalation vector: the definer's privileges
   plus a caller-controlled name resolution path.
2. **The owning role is `NOLOGIN` and owns nothing else.** It exists to own this one function.
   `EXECUTE` is granted to the runtime role and to nothing else.
3. **The regression test runs behind a real `NOBYPASSRLS` role.** Use the existing
   `rls_enforced_orm` fixture (`tests/portals/test_rls_spine.py`), which repoints Django's default
   connection at a `LOGIN NOSUPERUSER NOBYPASSRLS` role — so managers and FK descriptors, which is
   what the guard actually uses, all run behind the policy. A test on the default connection proves
   nothing here; that is exactly how three tests passed while guarding nothing.

### Three production constraints, checked 2026-09-09 after the probe

The minimal repro reproduced the policy shape, `FORCE ROW LEVEL SECURITY`, a real `NOBYPASSRLS`
role and the GUC set to the erasing tenant. Pressing on whether that was *enough* surfaced three
things it did not model, and two of them change the implementation.

1. **The owning role cannot be created by a Django migration.** Measured: a `CREATEROLE
   NOSUPERUSER NOBYPASSRLS` role attempting `CREATE ROLE ... BYPASSRLS` gets *"permission denied to
   create role — only roles with the BYPASSRLS attribute may create roles with BYPASSRLS"*. So the
   owning role belongs in the admin bootstrap beside the runtime role
   (`scripts/create_runtime_role.sql`), and the Django migration may only create the function and
   grant `EXECUTE`. A migration that tries to create the role fails at deploy time.

   **Implemented without the deviation, 2026-09-09.** An earlier attempt put a `CREATE ROLE ... IF
   NOT EXISTS` in the migration so a fresh developer database would still run `pytest`. That was the
   constraint's own warning shape, one failure mode softer, and it has been removed. The function
   and its role are now created by `scripts/create_erasure_guard.sql`, run by an admin after
   migrations (`docs/runbooks/deploy.md`); the test database runs the same script from
   `tests/conftest.py::django_db_setup`, so a fresh clone still runs `pytest` unchanged.
   `tests/infra/test_template.py::test_no_migration_creates_a_bypassrls_role` keeps it out.

   Removing the migration also removed `GRANT tehsil_erasure_guard TO migration_role`, which
   ownership transfer from a migration requires — see the residual-risk note below, which this
   closes rather than documents.

2. **The table owner's privileges are unpinned, which is itself a reason to reject the
   owner-owned function.** `create_runtime_role.sql` requires a `migration_role` and grants default
   privileges *for* it, but never constrains it to `NOSUPERUSER`/`NOBYPASSRLS`. So whether an
   owner-owned `SECURITY DEFINER` function bypasses RLS in production depends on an unconstrained
   deployment variable — it would be blind or not depending on how the database was bootstrapped.
   A security control must not rest on that.

   **Closed, 2026-09-09.** The bootstrap now refuses to run against a `migration_role` that is a
   superuser or `BYPASSRLS`, pinned by
   `tests/infra/test_template.py::test_bootstrap_refuses_an_unconstrained_migration_role`. This does
   not revive the owner-owned function — that option stays rejected on the measurement — it removes
   the variable from every other RLS outcome in the system.
3. **No connection pooler sits in front of Postgres.** The tasks connect straight to the RDS
   endpoint and no `CONN_MAX_AGE` is set, so `SET LOCAL`'s transaction scope behaves as written.
   A transaction-pooling proxy added later would need this path re-examined.

**Accepted residual risk:** the function is a small oracle. Anyone able to execute it can ask "does
user *N* hold an active membership anywhere" for arbitrary ids. That is one bit about an internal
identifier, callable only by the runtime role. Recorded as a deliberate widening rather than an
inherited one.

That "callable only by the runtime role" is now enforced by an explicit `GRANT EXECUTE` to the
runtime role and an assertion that `PUBLIC` lost it, in that order — see the two measured ordering
facts in CLAUDE.md. And the read is now **audited**: `advance_deletion` writes a `deletion.executed`
`AuditEvent`, plus `deletion.identity_retained` when the login legitimately survives. Without that,
the path satisfied only the first third of `phased requirements.md` §349, which requires privileged
cross-tenant operations to be least-privilege, reason-bound *and* audited.

**Two things security review corrected about that "callable only by the runtime role", 2026-09-09.**
Both measured on PostgreSQL 17, not argued.

- **The `REVOKE ... FROM PUBLIC` must precede the ownership transfer.** Postgres grants `EXECUTE` to
  `PUBLIC` on every new function, and after `ALTER FUNCTION ... OWNER TO` the migration role is no
  longer the owner; it can only revoke through its membership of the owning role, which a `NOINHERIT`
  migration role does not carry. Postgres then emits `WARNING: no privileges could be revoked` — and
  a warning does not fail a Django `RunSQL`. Measured: revoking after the transfer leaves
  `{=X/guard,guard=X/guard}` and `has_function_privilege('public', ..., 'EXECUTE') = true`; revoking
  before leaves `{guard=X/guard}` and `false`. The migration now revokes first and then *asserts* the
  outcome, because a silent no-op is the one failure this line cannot afford.
- **`GRANT tehsil_erasure_guard TO migration_role` is a `SET ROLE` away from `BYPASSRLS`.** The grant
  is structurally required — Postgres will not transfer ownership to a role the caller is not a
  member of — but the earlier claim that role attributes "are not inherited through membership" was
  half an answer. `SET ROLE tehsil_erasure_guard` is one statement. This is not new capability, since
  that credential owns every table and can `ALTER TABLE ... NO FORCE ROW LEVEL SECURITY` outright,
  but it is a quieter path, and the `NOSUPERUSER`/`NOBYPASSRLS` check on `migration_role` does not
  close it. Recorded rather than removed; removing it means creating the function from an admin
  session after migrations, which trades a documented path for a deploy step whose omission leaves
  the guard missing.

Also measured and fixed: `ALTER FUNCTION ... OWNER TO` requires the *new owner* to hold `CREATE` on
the schema. Without `GRANT CREATE ON SCHEMA public TO tehsil_erasure_guard` in the bootstrap, the
migration fails at deploy time with `permission denied for schema public` — invisible to CI, which
migrates as a superuser and skips the check. Verified end to end by replaying the migration SQL
verbatim under a `NOSUPERUSER NOINHERIT NOBYPASSRLS` migration role.

This query must run **unscoped by tenant** — its whole purpose is to see memberships at other
agencies, which a tenant-filtered manager hides. It therefore uses the base manager, not the
tenant-scoped default, and that deviation is deliberate and load-bearing: a tenant-scoped read here
returns nothing and the guard silently passes, scrubbing a live account. This is the same class of
failure as the missing `set_local_tenant` in the parent design, and it is the single most dangerous
line in this change.

Two additional refusals, both criterion 2:

- **Never scrub a `User` with `is_staff` or `is_superuser` set.** A Django admin account reaching
  this path means a misconfiguration, not an erasure. Refuse and record.
- **Never scrub when the erased membership's own `role` is not `STUDENT`.** Erasure is a student
  right; a counselor offboarding is a different operation.

### What is overwritten

Every concrete field on `auth.User`, classified explicitly:

| Field | Action | Why |
|---|---|---|
| `email` | `""` | the login address, directly identifying. Verified not `unique`, so blanking is safe — unlike `username` below |
| `first_name`, `last_name` | `""` | directly identifying |
| `username` | `f"deleted-{uuid4()}"` | **not `""`** — `username` is `unique`, so blanking works once and the second erasure in the same database raises an integrity error mid-transaction |
| `password` | `set_unusable_password()` | a credential, not a record |
| `is_active` | `False` | the account must not authenticate |
| `id`, `last_login`, `date_joined` | keep | structural or a bare timestamp; identifies nobody alone |
| `is_staff`, `is_superuser` | keep | the guard above refuses to scrub any user where these are set, so they are never reached with a true value |

Plus: **delete every `TOTPDevice` for that user.**

**Sessions need no code.** Django derives `get_session_auth_hash()` from the password hash, so
`set_unusable_password()` invalidates every existing session automatically. Writing session-flushing
code would be machinery for something the framework already does — criterion 8.

### When the guard blocks

The erasure is then knowingly partial, and **must say so**. `DeletionRequest` gains:

```python
identity_retained = models.BooleanField(default=False)
```

**This new field must be added to `KEEP["audit.DeletionRequest"]` in the same change.**
`DeletionRequest` is student-reachable, so the classification-completeness test fails until every
field on it is classified. That failure is the enforcement working exactly as designed — do not
route around it, and do not classify the field REDACT: erasing the record of what was erased defeats
the purpose.

Set `True` when the guard refuses. `state` still becomes `EXECUTED` — the tenant-scoped erasure did
complete, and retaining a login for a person who still has a live relationship elsewhere is lawful,
not a failure. What would be unlawful is *claiming* it was fully erased. This field is the
difference.

## Enforcement

Six tests. The first survives future Django upgrades; the sixth is the only one that can observe
the failure this document exists for.

1. **Every `auth.User` field is classified.** Enumerate the model's concrete fields and assert each
   appears in exactly one of the redact/keep lists. `auth.User` has gained fields across Django
   releases and will again; without this, a new field holding identity is invisible. This is the
   criterion-4 test and it is the whole reason the classification is a data structure rather than a
   sequence of assignments.
2. **The guard is not tenant-scoped.** Create the student in agency A and a second *active*
   membership for the same user in agency B, run the erasure from A, and assert the login survives
   and `identity_retained` is `True`. This test fails if someone "tidies" the unscoped query into
   the tenant-scoped manager — the failure this design is most likely to acquire later.
3. **Access is revoked.** After erasure, assert `request.student.active` is `False` — the property
   `middleware.py:64` depends on. Without this, a surviving login retains tenant access.
4. **The scrub happens and is complete.** Single-membership student: assert `email`,
   `first_name`, `last_name` are empty, `username` no longer matches the original, the password is
   unusable, `is_active` is `False`, and no `TOTPDevice` rows remain.
5. **The erasure is audited.** Two tests in `tests/audit/test_identity.py`: an executed erasure
   writes exactly `deletion.executed` with `actor=None` and `actor_kind="SYSTEM"`, and a retained
   identity writes a second `deletion.identity_retained` row. `DeletionRequest.state` cannot serve
   this purpose — it is a current-value field that says the request *is* `EXECUTED`, not that
   anything ran, and redaction rewrites the row around it.
6. **The guard works under real row-level security.** `tests/audit/test_identity_rls.py`, behind the
   `rls_enforced_orm` fixture: the same two-agency shape as test 2, but with Django's default
   connection repointed at a `LOGIN NOSUPERUSER NOBYPASSRLS` role and `app.tenant_id` set to the
   erasing agency. Test 2 passes on the ordinary suite whether or not the guard would work in
   production, because the test database role is `BYPASSRLS`; this one does not. Confirmed RED
   against the `_base_manager` query (`assert True is False` — it scrubbed a login still in use) and
   GREEN against the `SECURITY DEFINER` function. Its second case pins the other direction: reading
   across tenants must not stop erasure working when nothing survives.

## What this does not do

- **Does not give `advance_deletion` a caller.** The operator console is a separate design, and it
  depends on this one landing first.
- **Does not add a grace period.** The agreed 14-day reversal window belongs with the console that
  schedules erasures; it changes *when* `EXECUTED` is reached, not what happens at it.
- **Does not enforce one-agency-per-student in the schema.** A partial unique index would make that
  product rule real, following the `CounselorAssignment` precedent, but it is a cross-tenant
  constraint that deserves its own change and does not remove the need for the guard here — the
  guard also covers a student who is also a counselor.
- **Does not close `documents.EuropassRenderCache`.** It stores a SHA-256 of the student's canonical
  CV payload with no FK to `Membership`, so it is invisible to the completeness test. The fix is to
  add the FK, which is a small separate change.

## Open question for review

1. The criteria-1-versus-2 ranking above. Everything else follows from it.
