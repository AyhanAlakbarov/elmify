---
paths:
  - "apps/*/migrations/**"
  - "scripts/*.sql"
---

## Migrations: squash once, in the one window where it is cheap

There is no production database, so the schema is free — rename,
drop, restructure a model and let Django write the migration. Nothing about the AWS
design is shaped by the count; the only deploy-time constraint is *who* runs them
(`tehsil_migration`, non-superuser, `NOBYPASSRLS`).

**Before launch, squash to one initial migration per app.** Not done yet, deliberately,
and the reason is the cost, not the value:

- **A large share of the migrations carry hand-written `RunSQL`/`RunPython`** — the RLS policies,
  `FORCE ROW LEVEL SECURITY`, tenant guards, per-table GRANTs. Django's regenerated
  initial recreates tables and constraints and **none of that**. A squash is therefore a
  hand-merge of the highest-risk SQL in the repo, and per `.claude/rules/row-level-security.md` **no test
  can catch a mistake in it** — the test role bypasses RLS. Verify against the
  `runtime_connection` / `rls_enforced_orm` fixtures or you have verified nothing.
- **Every unmerged branch carries migrations on the current chain.** A squash invalidates all of them at once.

So the window is: tree quiet, nothing long-lived in flight, **before the first real
database exists**. Earlier means doing it twice; later means never, because the first row
of production data ends it.

**It does not fix branch collisions, and squashing for that reason is a mistake.** Two
branches editing the same chain in parallel collide at any migration count — measured
2026-09-15, when master renumbered `funding/0030_cv_directives_undecided_unreadable` to
`0031` while the letter-engine branch built `0031_application_prompt` on top of the old
name. The merge was textually clean and the dependency pointed at a node that no longer
existed. What caught it was `makemigrations --check` in CI, which is already there.
