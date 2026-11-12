---
paths:
  - "apps/research/**"
  - "tests/research/**"
  - "apps/funding/**"
---

## The institution-safety screen was removed — 2026-09-14, and this is the record

**Deleted:** `apps/research/registers.py` (the DEQAR and WHED readers), `manage.py
refresh_register`, `manage.py load_institution_identifiers`,
`docs/research/institution-identifiers.csv`, the `InstitutionIdentifier`, `RegisterListing`
and `RegisterCoverage` models (migration `0032`), `Institution.kind`/`parent`, and six test
modules. ~2,900 lines. **Do not rebuild any of it without reading this section first.**

The screen was deleted unread: nothing ever called it. It left one door open — a search-found
organisation could mint an `Institution` with nothing marking it unconfirmed — and registers were
to return only as a product decision. Both are settled below: recognition returned 2026-09-26 as
evidence behind the provenance gate, not as that screen. **Do not revive `registers.py`.**

**The expensive part was never the code.** The research, the measurements and IAU's consent
survive in `docs/superpowers/research/2026-08-31-*`, `2026-09-11-whed-recon.md` and the specs
`2026-08-31-institution-safety-screen-design.md` / `2026-09-11-deqar-register-adapter-design.md`
— including the rehearsal numbers worth having if this ever returns: 375 MB peak RSS for DEQAR's
103 MB file, and S3 bucket versioning being load-bearing (an unversioned bucket silently records
the string `"null"` for every snapshot). Those documents are now **history, not plans**.

**Two designs this supersedes in part.** The 2026-09-14 EMJM partner-source design keeps its
purpose — *which universities award a joint programme*, for the student's report and
`evaluation.py`'s LOCATION gate — but its join no longer goes through a register: EACEA already
supplies name, country, city and website per organisation, so a binding resolves against our own
`Institution` rows directly. And the 2026-09-14 scheduled-work design's `refresh_register`
schedule (§5.2) is void; `catalog_ingestion` itself was dropped 2026-09-25, and `runtime_engine`
writes the other catalogue tables.

### Recognition returns behind the provenance gate — 2026-09-26

Owner decision, 2026-09-26: recognition returns, to keep fake universities from students and to
judge recognition at home in Azerbaijan. This section's condition for bringing registers back ("a
product decision") is met. Registers return as **evidence sources behind a gate**, not as the
deleted screen (`docs/superpowers/specs/2026-09-26-institution-provenance-gate-design.md`, plan
`docs/superpowers/plans/2026-09-26-provenance-gate.md`). The open door above is closed at
`candidate_pool`. A programme is admissible only when its OWN evidence domain
(`Program.evidence_domain`) is a `RECOGNISED` body's bound domain. The `Institution` row and
`Institution.official_website` decide nothing, because they are found by name.

- **The switch is `PROVENANCE_GATE_ENFORCED`, on in deploys since 2026-10-03 (template default `1`; unset, as in local and test runs, it is off) (verified-only: no
  unconfirmed body reaches a student, whoever placed it).** A database that held data before the
  gate: set it off, run `backfill_evidence_domain` then `provenance_check --all`, then turn it on.
  One template parameter, `ProvenanceGateEnforced`, feeds web and worker; order: `deploy.md`.
- **Forward rule (§7.5):** whatever first creates a `portals.Application` checks the candidate's
  tenant copy `provenance_reason_code` and refuses a BLOCKED one. `portals.applications.add_application` is that creator and refuses BLOCKED (and,
  while the gate is enforced, anything not RECOGNISED), the same check as `replace_candidate`.
- **Schedule requirement (§7.6):** `ProvenanceRecheckRule` (daily, `provenance_recheck`) ships
  ENABLED and must stay so before any real student. Without it UNCONFIRMED is never retried and a
  good school is lost silently.
- **The State Programme PDF is the one stated exception to "PDFs go to Firecrawl" (§6):** a data
  table, parsed as bytes through `fetch_data_file` into a reviewed closed list. It is never a page
  read. Not built yet; Plan 2 needs it.
- **Jev goes through OpenRouter** (`apps/research/jev.py`, the provenance vetoes' client;
  `JEV_API_KEY` from `OPENROUTER_API_KEY`; `JEV_MODEL` pinned). It is a second Jev client beside
  the typed-decision layer's `apps/research/decisions.py`; unifying them is an open design
  decision. It only ever vetoes, and it is skipped and recorded when unkeyed.
- **Register terms are recorded, never a gate** (owner, 2026-09-27). HRK Hochschulkompass permits
  personal use only and is read anyway; its data file sits on `hs-kompass.de`, so it counts only
  because the vouched `hochschulkompass.de` downloads page links it. Korea's register needs no key
  (anonymous JSON, served as `text/html`).
- **Coverage is five countries** (GB, DE, KR, TR, AZ). A body elsewhere is UNCONFIRMED with reason
  `no_register`, visibly, until a register or WHED is added.
- **Verify, don't assume:** verdict writes are proven as `runtime_engine` (`role_connection`), and
  the sweep and the named-programme worker through `rls_enforced_orm`, because the test role
  bypasses both.
