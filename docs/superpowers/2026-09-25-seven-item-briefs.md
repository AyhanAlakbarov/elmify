# The seven remaining funding-engine items — paste-ready briefs

Each block below is a complete brief for one **cloud session**. Paste one per session. They write a
plan; they do not write application code. The spec is
`docs/superpowers/specs/2026-09-22-funding-search-engine-master-design.md`, §16 holds the build
order, and every item carries a measurement gate the plan must end with.

**Rules that go in every session** (repeated inside each brief, so a paste is self-contained):

- Use the `superpowers:writing-plans` skill and follow it exactly. No placeholders.
- Do not edit anything under `docs/superpowers/specs/` — several sessions edit those in parallel.
- Do not modify `apps/`, `tests/` or `config/`. Plans only.
- Never hard-code a migration number; instruct the executor to check the app's real leaf and expect
  a merge migration. `research` is at `0009_site_job_record_rls` as of 2026-09-25.
- Any new table states whether it is tenant-scoped, shared catalogue or platform-only, carries its
  RLS policies in the same migration, and is added to `tests/tenancy/test_database_isolation.py`.
  Read `CLAUDE.md`'s RLS section: the test role bypasses RLS, so verification goes through
  `runtime_connection` / `rls_enforced_orm` or it has verified nothing.
- Read the real code before planning. Master already has `apps/research/` (the fetch engine, the
  register ladder, the funnel), `apps/funding/` (the reader, the pool, the gates).
- Branch `claude/plan-<item>`, commit the plan, push, open a PR, do not merge.

---

## Item 7 — enumerators

Plan the closed lists for two launch countries (§16 item 7, §6.2): the country-less
**intergovernmental and regional fund** list (global, cell-tagged, never sized to one corridor —
World Bank, IsDB, ADB, AfDB, OPEC Fund, UNESCO, Aga Khan), Wikidata and ROR as sources, the EACEA
project API with its EMJM partner binding, the register survey per corridor country, and curated
national files. Scope each source to what it can answer alone. Gate: 100% enumerated with read
states recorded.

## Item 8 — the resolver

Plan name→site resolution as §6.5 specifies: the `names` store, the six data rules, the Diffbot
residue path, and what stays unresolved and why. Master already has `apps/research/domains.py`
(registrable domains, free-mail detection, `email_domain`) and the rung-0 e-mail resolution from the
register ladder — build on those rather than a parallel implementation. Gate: a fresh-script
hold-out set, so the plan must say how one is assembled and what result would fail it.

## Item 10 — the rest of the sweep harness

The register-ladder half landed with item 6a. Plan what remains (§6.3, §6.7): the page-voiced
**angle-set generator** per (country, family), the seven-lever query recipe, the language loop from
Wikidata P37 plus English, per-angle and per-`(family, provider)` first-discoverer tallies, and the
two stop rules — the economic one and three consecutive batches with no new verified host. Depends
on items 7 and 8 for its denominator; say so and plan against their interfaces.

## Item 11 — the verification ladder

Plan §9.2's cycle verification: `FundingCycleVerification` with `cost_usd`, the own-site-plus-one-hop
evidence rule, cadence scheduling (monthly, weekly in the two months before last cycle's call date,
daily within 14 days) and expiry. `apps/funding/validity.py` already holds `cycle_validity` as a pure
function — the plan extends the evidence side, not the decision side.

## Item 12 — the human resolution queue

Plan `ResolutionItem` as a **platform-only** table with the four kinds of §11, the owner console
surface, and its writers. Find the callers that file consultant tasks today (`pipeline.py`'s blocked
sources, `manage.py funding_review`) and say which of them become queue writers. It is a queue, not a
ledger: state what moves an item out of it and who may do that. Platform-only is a deliberate third
RLS case — justify it.

## Item 13 — the card the reader owes

Plan the award card's own fields (§8.3, §10.4): amount, currency, period, duration,
`required_documents`, `timing`, `cycle`, and `contact` (an **office** address or contact page,
quote-verified on origin, never a named person's address — §9.2 and decision 39). **Read the typed
decisions spec first**: `docs/superpowers/plans/2026-09-23-reader-and-multilingual-layer.md` rewrites
how the reader selects and classifies sentences, and this item writes fields through it. Say
explicitly which parts must wait for that plan and which can land before it.

## Item 14 — demand cells and coverage

Plan §10.5 and §10.6: profile → cell, `CellCoverage`, the bounded per-cell sweep a thin cell
triggers, the per-student $50 cycle wallet as a depleting budget keyed `(student, intended_intake)`,
the tailoring rule over the consultation answers (three bins: query words, output filters, never),
and the coverage line that names the rung it reached. Depends on item 10's tallies.

## Item 15 — cost: Batch/Flex and the cheap first read

Plan the cost work of §13 and §8.9: batch or flex pricing where a call is not latency-bound, prompt
caching, and the cheap first read that decides whether an expensive read is worth making. It runs
**beside** the other items rather than after them, so the plan must not assume any of them landed.
Measure before and after per changed page; a saving nobody measured is not a saving.
