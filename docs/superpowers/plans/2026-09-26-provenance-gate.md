# Institution Provenance Gate (Plan 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** No programme or award reaches a student's pack unless the body behind it is `RECOGNISED` by evidence the attacker cannot write, while a data gap never condemns a real school.

**Architecture:** A body is a `research.Organisation`, keyed by registrable domain. A worker-only job (`provenance_check`) gathers evidence for each body in play: reviewed lists, registers found through ENIC-NARIC, ROR identifiers, government zones, one-hop structural links, a mill list, content vetoes and RDAP. A pure function `decide()` then turns that evidence into a `ProvenanceVerdict` row, written only by `runtime_engine`. `candidate_pool` filters on those rows inside its query, behind `PROVENANCE_GATE_ENFORCED`, and each programme is judged by its own evidence domain (`Program.evidence_domain`), never by the `Institution` row. Tenant-side copies (`RecommendationCandidate.provenance_reason_code`, `RecommendationRun.pending_bodies`, `PackVersion.change_notes`) let the web tier show outcomes without reading the catalogue. A daily sweep carries verdict changes into published packs.

**Tech Stack:** Django 5.2, PostgreSQL 17 (RLS + table grants), Python 3.14, tldextract 5.3.2, lxml, pytest-django, uv, ruff (lint only), mypy, CloudFormation (`infra/template.yaml`).

**Spec:** `docs/superpowers/specs/2026-09-26-institution-provenance-gate-design.md` (the authority). This plan covers §3–§8, §11, §12's Plan 1 order, the §9.6/§15 document corrections and §13.8's origin verification. It does **not** cover §9 (the Azerbaijan outlook, Plan 2), and it deliberately leaves `RecommendationCandidate.recognition_outlook` out; Plan 2 adds it.

## Global Constraints

- **No model call on the admit path.** Nothing that can make a body `RECOGNISED` calls a model. Jev is called only by the two content vetoes (spec §5.4 rules 3 and 4).
- **Content checks veto only.** Content checks (Jev) can only lower a verdict, never raise one. When Jev is unconfigured they are skipped and recorded as skipped (`evidence["content_checks"] == "skipped"`).
- **Absence is never `BLOCKED`.** A missing register row, a list that disagrees or a failed lookup gives `UNCONFIRMED` with a reason from spec §4.1.
- **Never a name match.** A body binds to a domain only through an identifier or a reviewed closed-list row. A name is only ever display text or an origin-verification check of a row a person already mapped.
- **The worker computes verdicts, the web tier never does.** Verdicts are computed by the worker (`runtime_engine`), never on the web tier. A web path reads only tenant copies: `provenance_reason_code`, `pending_bodies` and `change_notes`.
- **Catalogue tables follow the CLAUDE.md recipe.** That means the `shared_catalog_select` read policy, the `runtime_engine_write` policy, and `REVOKE ALL ... FROM runtime_web`, sequences included. Grants and RLS are proven through `role_connection` / `rls_enforced_orm`, never through the superuser test role.
- **Per-tenant loops set both filters.** Each iteration enters `tenant_scope(tenant_id)` AND calls `set_local_tenant(tenant_id)` inside its transaction.
- **The pool filter sits inside the query.** The `candidate_pool` provenance filter goes before `order_by(...)[:limit]` and sits behind `settings.PROVENANCE_GATE_ENFORCED`. It is enabled only after the backfill (`provenance_check --all`, Task 12). The setting defaults to off.
- **Transports follow spec §6.** Pages (ENIC-NARIC country pages, HTML registers, Wikipedia revisions, recogniser pages) go through `apps.research.fetch.fetch_page`. Data files (CSV/TSV/JSON registers, the IANA RDAP bootstrap, registry RDAP answers) go through `egress.fetch_data_file`. That function gains a per-call `max_bytes` (default stays 10 MB) and the `application/rdap+json`, CSV and XLSX content types. Jev goes through `egress.fetch_json_api`, a contracted keyed API.
- **Jev goes through OpenRouter.** The endpoint is `{settings.JEV_BASE_URL}/v1/systemone` (default base `https://openrouter.ai/api`). The key is `settings.JEV_API_KEY`, read from env `OPENROUTER_API_KEY`. The model is pinned to `settings.JEV_MODEL` (default `jev-1.13`, never an alias), and thresholds are pinned to that model. One Jev client serves the repo (`apps/research/jev.py`). Only page text is ever sent, never student data.
- **No live network in tests.** Every test stubs fetches. The only exceptions are tests marked `@pytest.mark.live`, which `addopts` deselects by default.
- **Test database:** `POSTGRES_DB=tehsil_provenance_gate`, with `--create-db` on the first run of each task.
- **Never run `ruff format`.** The tree is not formatter-clean. The gate is lint only.
- **Research migrations never depend on funding migrations** (research/0003's `InvalidMigrationPlan`, restated in research/0010's header).
- **Checks after every task, all four must pass:**
  - `uv run ruff check apps config tests scripts`
  - `uv run mypy apps config`
  - `uv run python manage.py makemigrations --check --dry-run`
  - `POSTGRES_DB=tehsil_provenance_gate uv run pytest -q --create-db`

## Review Focus

These are the conditions the spec implies but does not spell out, most likely to bite first. Each one has a pinning test in the task named.

1. **A register page changes its layout.** The list anchor disappears or zero rows parse. Expected: the load fails loudly (`RegisterShape`) and the body gets `lookup_failed`, never `absent_from_register` for every institution in that country. Pinned in Task 6 (`test_a_page_without_the_list_anchor_fails_loudly`, `test_zero_parsed_rows_is_a_shape_error_not_an_empty_register`).
2. **A recogniser's homepage redirects off its main host** (a parked or expired domain). Expected: no vouch. The redirected page is not the recogniser. Pinned in Task 10 (`test_a_recogniser_that_redirects_off_its_host_vouches_for_nothing`).
3. **Outages during a re-check of a recognised body.** Jev, RDAP or IANA may be down. Expected: the body stays `RECOGNISED`, and the outage is recorded in `evidence`. An outage never downgrades and never blocks. Pinned in Task 12 (`test_outages_never_downgrade_a_recognised_body`).
4. **Running the job or the sweep twice.** Expected: no duplicate `ProvenanceVerdictChange` rows and no second pack version. Pinned in Task 2 (`test_an_unchanged_verdict_writes_no_second_change_row`) and Task 16 (`test_a_second_sweep_changes_nothing`).
5. **A HOLDER award whose organisation was unkeyed by `rederive_domains`** (organisation now NULL). Expected: excluded under the gate, and coded `no_holder_body` when the gate is off. It never crashes pack building. Pinned in Task 13 (`test_an_award_with_no_holder_body_is_excluded_and_coded`).

## Decisions this plan takes where the spec leaves a choice

- **Migration numbers.** The storage migrations are `research/0011_provenance.py` and `funding/0051_provenance.py`, the next free numbers on this branch. The implementer re-checks `ls apps/research/migrations apps/funding/migrations` before generating. If master moved, take the next free numbers and keep the names.
- **Absence of a verdict row means `not_evaluated`.** The migration inserts no rows (spec §7.7 says "every existing body at not_evaluated"). Reading a missing row as `not_evaluated` is equivalent and avoids a second writer in `record_organisation`.
- **"Bodies in play" are the only bodies checked.** These are: domains of programme evidence, HOLDER-award organisations, and bodies recorded for a named programme. `provenance_check --all` does not walk every `Organisation`. VGM alone holds 4,076 foundations, and vouching can cost up to 11 vendor fetches per body.
- **A cycle is `PROVENANCE_CYCLE_DAYS = 30`.** It governs register reloads, the re-check of `RECOGNISED` bodies, and the two-cycle removal in the sweep. Re-check schedule by verdict:
  - `UNCONFIRMED` because of `lookup_failed`, `register_not_loaded` or `not_evaluated`: re-checked after 1 day.
  - Any other `UNCONFIRMED`: re-checked after 7 days.
  - `BLOCKED`: never re-checked.
- **Which lists count as evidence is data, not rungs.** Each list is named in the new file `docs/research/provenance-sources.csv`, with a role of `register`, `curated_list` or `funder_list`, keyed by its `closed-lists.csv` slug. Register-read settings live there too: format, fields, list anchor, ENIC-NARIC page and per-source `max_bytes`. This keeps the `closed-lists.csv` column contract (an exact match on `_REGISTRY_COLUMNS`) untouched.
- **A register is read by code only when its terms are `OPEN`.** This matches the repo's existing rule: `ClosedList.Terms.UNREAD` lists are "never read by an adapter".
- **Structural terms, excluded terms, hosting platforms and government zones are code constants pinned by tests.** They are in Tasks 1, 5 and 10. A government zone ships only with a registry citation fetched at plan time (see the spec corrections below).
- **Content-veto precedence covers `accreditation_mill` too.** Spec §5.4 states the precedence for rules 3 and 4 only. A recognised body whose page names a deny-listed accreditor becomes `UNCONFIRMED(veto_conflict)`, not `BLOCKED`, for the same reason: vendor wording must never condemn a real university.
- **RDAP failures never change a verdict.** RDAP is a takeover signal, not recognition. A failed lookup is recorded as `rdap.status = "failed"` and retried next cycle.
- **The sweep marks a withdrawn candidate `REJECTED`.** Otherwise the student's "considered" list, which shows run candidates outside the pool, would show a `BLOCKED` programme. The sweep also writes an `AuditEvent` `candidate.withdrawn`. Notes carry an `action` key (`removed` or `kept`) beside the spec's `{candidate_name, reason_code, at}`.
- **The sweep keys on a tenant copy of the body id.** `RecommendationCandidate` gets `provenance_body_id` (a UUID, not an FK), alongside `provenance_reason_code`.
- **`replace_candidate` refuses an unchecked candidate only when the gate is enforced.** A `BLOCKED` code is refused always. Before enforcement no candidate carries a code.
- **Jev thresholds are pinned to `settings.JEV_MODEL`.** Both vetoes act at P(yes) ≥ 0.85, the typed-decisions spec's §3.1a band for "actions that cost". If the reply's `model` field does not name the pinned model, the veto is skipped and recorded.

## Spec corrections found while planning (each is repeated in the task it affects)

1. **§5.1/§5.7 rungs.** `az_outbound_gov`, `az_bilateral` and `tr_bilateral` are rung 3 in `docs/research/closed-lists.csv`, so "REGISTERED counts only at rung ≤ 2" would exclude three of the four lists §5.7 names as evidence. Evidence lists are therefore named per list in `provenance-sources.csv`, not by rung (Task 5).
2. **§3 joint rule 2 (EACEA `RegisterEntry`).** No `Program`↔`RegisterEntry` link exists. `apps/research/eacea.py`'s docstring says "which `Program` row a project is" is a person's decision. EACEA partners become `RECOGNISED(funder_list)` bodies, keyed on their PIC and listed website, so joint rule 1 covers a joint programme on a partner's domain. A programme on a consortium's own domain stays `UNCONFIRMED` until a reviewed closed-list row maps that domain (Task 5).
3. **§7.4 named programmes.**
   - No name→site resolver exists. `TavilyProvider.candidates` deliberately does not choose, per its docstring, and choosing by name would be the name match §5.2 forbids. The site is the counsellor's verified `source_url`, so the worker check is queued by `resolve_named_program`, not by `consider_named_program`.
   - `replace_candidate` is a student action (`replace_candidate_view`, `actor=student`). The counsellor's step is `resolve_named_program` (Task 14).
4. **§5.1 known-answer registers.**
   - HRK Hochschulkompass: its imprint (read 2026-09-26) says the service is free "zum persönlichen Gebrauch" and every other use, "insbesondere die der kommerziellen Nutzung (auch einzelner Teile)", needs the Stiftung's permission. It is not shipped, so German bodies stay `register_not_loaded`. This is a new open question beside §13's.
   - YÖK's recorded list URL (`https://www.yok.gov.tr/universiteler/universitelerimiz`) answered 404 on 2026-09-26. It is not shipped.
   - SFC is not linked from ENIC-NARIC's UK page, which links `gov.scot`'s policy page, so it is named by hand.
   - OfS is linked from ENIC-NARIC and published under the OGL, so it is shipped.
   - SFC is under OGL v3, so it is shipped.
   - **Korea needs no key.** Spec §13.7's blocker is void. data.go.kr's standard-data download (`/download/standard.json?publicDataPk=15107736...`) answers an anonymous GET: 1,995 rows, 1,715 with `HMPG_ADDR`, served as `text/html` although the body is JSON (verified by the coordinator and re-measured here, 2026-09-26). Korea is outside ENIC-NARIC, so it is named by hand, with KOGL terms, and it is shipped.
   - Known-answer tests for TUM and METU run on captured fixtures with test-local source rows. KENTECH's runs on a captured fixture of the shipped Korean source (Task 6).
5. **§9.6 documents.** The master spec (`2026-09-22-funding-search-engine-master-design.md:236`) carries the same "TKTA publishes no list" claim, and the enumerators plan carries it twice (lines 803 and 2083). All three are corrected (Task 18).
6. **§5.4 / §11 mill list.**
   - The Wikipedia list carries names, not domains, so `docs/research/mill-list.csv` is a reviewed name→domain file. The revision is pinned at 1376085262 (2026-09-22).
   - A ROR name search (2026-09-26) verified 6 of the 13 known-answer mills, with their domains: Bircham, AIU, Warnborough, IIU, Breyer State and American World University. It did not find St Clements.
   - Selinus is absent from that revision. Pacific Western is listed as "American Pacwest International University".
   - The other seven wait for a reviewed domain. Their known-answer tests pin the mechanism with synthetic domains (Task 9).
7. **§5.7 government zones.** Only zones whose registry citation was fetched on 2026-09-26 ship: `gov`, `gov.tr`, `go.jp`, `go.kr`, `europa.eu` and `auswaertiges-amt.de`. The others the spec names (`gov.uk`, `gov.az`, `gouv.fr`, `gov.cn`, `gob.es`, `gob.mx`, `bund.de`, `bmbf.de`, `gc.ca`) are each added later with a citation, as the spec requires (Task 5).
8. **§5.6 private suffixes are not enough.** `include_psl_private_domains=True` fixes `github.io` and `blogspot.com` but leaves `x.wordpress.com → wordpress.com` and `sites.google.com → google.com` (measured, tldextract 5.3.2). The hosting-platform list is also passed as `extra_suffixes`. Bodies merged under `google.com` before the fix cannot be detected (Task 1).
9. **Owner decision relayed 2026-09-26: Jev goes through OpenRouter.**
   - `JEV_BASE_URL`, `JEV_API_KEY` (env `OPENROUTER_API_KEY`) and `JEV_MODEL` replace `TYPESAFE_API_KEY`.
   - The unexecuted plan `docs/superpowers/plans/2026-09-23-decision-layer-and-rule-grammar.md` still names `TYPESAFE_API_KEY`/`TYPESAFE_MODEL`. It needs the same rename when executed (Task 8).

---

## File Structure

**New (apps):**
- `apps/research/provenance.py` holds the verdict vocabulary: reason sets, bilingual wording, `evidence_of`, the pure `decide()`, `record_verdict()` and the tenant-copy helpers (`provenance_of_program`/`_award`, `programme_verdict`, `recognition_note`).
- `apps/research/recognition.py` covers who may vouch: `provenance-sources.csv`, list/partner/ROR recognitions, government zones, origin verification, the ENIC-NARIC check, register parsers and loaders, and register state.
- `apps/research/jev.py` is the one Jev client, reached through OpenRouter.
- `apps/research/blocking.py` holds the mill list, accreditation-mill deny list, veto sentence pickers, Jev vetoes, the body page texts and the Wikipedia diff helpers.
- `apps/research/vouch.py` implements one-hop structural vouching.
- `apps/research/rdap.py` holds the IANA bootstrap and the registration date lookup.
- `apps/research/provenance_job.py` holds `check_body`, `bodies_in_play`, `due`, `run_checks`, `check_named_program` and `Deps`.
- `apps/research/provenance_sweep.py` carries verdict changes into packs and pending runs into re-runs.
- Management commands: `rederive_domains`, `verify_list_origins`, `mill_list_diff`, `provenance_check`, `provenance_pack_sweep`, `provenance_recheck`.

**New (data):**
- `docs/research/provenance-sources.csv`
- `docs/research/mill-list.csv`
- `docs/research/accreditation-mills.csv`
- `docs/research/closed-lists/national_scholarship_agencies.csv`

**Modified:**
- `apps/research/`: `hosts.py`, `models.py`, `closed_lists.py`, `catalog.py`, `ror.py`, `egress.py`, `services.py`, `spine.py`, `schemas.py`, `management/commands/run_research_worker.py`
- `apps/funding/`: `models.py`, `pool.py`, `services.py`, `views.py`
- `apps/documents/`: `research_fit/jev.py`, `management/commands/draft_letter.py`, `document_worker.py`
- `apps/audit/redaction.py`
- `config/settings/base.py`
- `infra/template.yaml`
- `docs/research/closed-lists.csv`
- `CLAUDE.md`
- `docs/runbooks/deploy.md`
- The corrected documents of Task 18

**Tests:**
- New:
  - `tests/research/provenance_helpers.py` (shared builders)
  - `tests/research/test_rederive_domains.py`
  - `tests/research/test_provenance_storage.py`
  - `tests/research/test_program_evidence.py`
  - `tests/research/test_provenance_decide.py`
  - `tests/research/test_recognition_lists.py`
  - `tests/research/test_provenance_registers.py`
  - `tests/research/test_ror_binding.py`
  - `tests/research/test_jev_client.py`
  - `tests/research/test_blocking.py`
  - `tests/research/test_vouch.py`
  - `tests/research/test_rdap.py`
  - `tests/research/test_provenance_check.py`
  - `tests/funding/test_pool_gate.py`
  - `tests/funding/test_named_program_gate.py`
  - `tests/research/test_provenance_sweep.py`
  - `tests/research/test_provenance_live.py` (`-m live` only)
- Modified:
  - `tests/research/test_hosts.py`
  - `tests/research/test_egress.py`
  - `tests/documents/research_fit/test_jev.py`
  - `tests/documents/research_fit/test_live.py`
  - `tests/documents/test_draft_letter_command.py`
  - `tests/documents/test_document_worker.py`
  - `tests/infra/test_template.py`

---

### Task 1: The registrable-domain fix, hosting platforms and re-derivation

**Files:**
- Modify: `apps/research/hosts.py`
- Create: `apps/research/management/commands/rederive_domains.py`
- Test: `tests/research/test_hosts.py`, `tests/research/test_rederive_domains.py`

**Interfaces:**
- Consumes: nothing new.
- Produces:
  - `apps.research.hosts.HOSTING_PLATFORMS: tuple[str, ...]`
  - `apps.research.hosts.USER_CONTENT_LABELS: frozenset[str]`
  - `apps.research.hosts.registrable_domain(value: str) -> str` (private suffixes and platforms now suffixes)
  - `apps.research.hosts.is_hosting_platform(domain: str) -> bool`
  - `apps.research.hosts.is_institutional_url(url: str, domain: str) -> bool`
  - The `manage.py rederive_domains` command

Spec correction for this task: private suffixes alone leave `x.wordpress.com → wordpress.com`, `z.weebly.com → weebly.com` and `sites.google.com → google.com` (measured, tldextract 5.3.2), so the platform list is also passed as `extra_suffixes`. A body merged under `google.com` before the fix is indistinguishable from Google itself and cannot be detected. There is no production database, so such dev data is re-created.

- [ ] **Step 1: Write the failing tests**

Append to `tests/research/test_hosts.py`:

```python
from apps.research.hosts import HOSTING_PLATFORMS, is_hosting_platform, is_institutional_url


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        # Spec §5.6's measured table: one blog anchored all of blogspot, and
        # one Russian university stood for all of edu.ru.
        ("foo.github.io", "foo.github.io"),
        ("bar.blogspot.com", "bar.blogspot.com"),
        ("tspu.edu.ru", "tspu.edu.ru"),
        # Not on the PSL's private section: only extra_suffixes separates them.
        ("x.wordpress.com", "x.wordpress.com"),
        ("z.weebly.com", "z.weebly.com"),
        ("y.wixsite.com", "y.wixsite.com"),
        # A platform root names the landlord, never a publisher: unkeyable.
        ("wordpress.com", ""),
        ("sites.google.com", ""),
        ("https://sites.google.com/view/some-university", ""),
    ],
)
def test_private_suffixes_and_hosting_platforms_key_their_tenants(value, expected) -> None:
    assert registrable_domain(value) == expected


def test_the_hosting_platform_list_is_pinned() -> None:
    assert HOSTING_PLATFORMS == (
        "github.io", "gitlab.io", "blogspot.com", "wordpress.com", "wixsite.com",
        "weebly.com", "sites.google.com", "squarespace.com", "webflow.io",
        "netlify.app", "vercel.app", "pages.dev", "herokuapp.com",
        "firebaseapp.com", "web.app", "tumblr.com", "medium.com", "substack.com",
        "notion.site", "000webhostapp.com",
    )


@pytest.mark.parametrize(
    ("domain", "expected"),
    [
        ("foo.github.io", True),
        ("bar.blogspot.com", True),
        ("x.wordpress.com", True),
        ("github.io", True),
        ("tum.de", False),
        ("google.com", False),
    ],
)
def test_a_body_on_a_hosting_platform_is_recognised_as_one(domain, expected) -> None:
    assert is_hosting_platform(domain) is expected


@pytest.mark.parametrize(
    ("url", "domain", "expected"),
    [
        ("https://www.tum.de/en/studies/msc", "tum.de", True),
        ("https://www.cit.tum.de/cit/studium/", "tum.de", True),
        ("https://tum.de/", "tum.de", True),
        ("https://blogs.tum.de/robotics/", "tum.de", False),
        ("https://wiki.cs.tum.de/x", "tum.de", False),
        ("https://students.tum.de/club", "tum.de", False),
        ("https://people.tum.de/~ada", "tum.de", False),
        ("https://www.tum.de/~ada/msc", "tum.de", False),
        ("https://fake-tum.example/msc", "tum.de", False),
        ("https://foo.github.io/msc", "foo.github.io", False),
        ("https://www.tum.de/x", "", False),
    ],
)
def test_institutional_urls_exclude_user_content(url, domain, expected) -> None:
    assert is_institutional_url(url, domain) is expected
```

Create `tests/research/test_rederive_domains.py`:

```python
"""rederive_domains: re-key what the old suffix rule merged (spec §5.6)."""

from io import StringIO
from uuid import uuid4

import pytest
from django.core.management import call_command
from django.utils import timezone

from apps.funding.models import (
    FundingOpportunity,
    FundingOpportunityEvidenceClaim,
    OfficialEvidenceClaim,
    OfficialSource,
    OfficialSourceSnapshot,
)
from apps.research.models import (
    Organisation,
    OrganisationDomain,
    OrganisationIdentifier,
    RegisterEntry,
    RegisterEntryPartner,
)

pytestmark = pytest.mark.django_db


def _snapshot_claim(url: str) -> OfficialEvidenceClaim:
    source = OfficialSource.objects.create(
        canonical_url=url, publisher="x", source_type=OfficialSource.Type.FUNDER
    )
    snapshot = OfficialSourceSnapshot.objects.create(
        source=source, s3_key="k", s3_version_id="1", sha256="a" * 64, final_url=url,
        redirect_chain=[], retrieved_at=timezone.now(), admissions_cycle="2027",
        content_type="text/html", byte_size=1,
    )
    return OfficialEvidenceClaim.objects.create(
        source=source, snapshot=snapshot, claim="grant", evidence_strength="DIRECT",
        visibility="STUDENT_FACING", claim_class="FUNDING", last_checked_at=timezone.now(),
    )


def _merged_blog_body() -> Organisation:
    body = Organisation.objects.create(
        primary_domain="blogspot.com", name="A Blog", kind="PRIVATE_FOUNDATION"
    )
    OrganisationDomain.objects.create(organisation=body, registrable_domain="blogspot.com")
    OrganisationIdentifier.objects.create(organisation=body, scheme="WIKIDATA", value="Q1")
    return body


def test_a_body_merged_under_a_platform_root_is_unkeyed_and_its_links_cleared() -> None:
    body = _merged_blog_body()
    award = FundingOpportunity.objects.create(
        canonical_key=f"read:holder:{uuid4()}", name="Blog Grant", family="PRIVATE_FOUNDATION",
        scope_type="HOLDER", holder_domain="blogspot.com", organisation=body,
    )
    FundingOpportunityEvidenceClaim.objects.create(
        opportunity=award, evidence_claim=_snapshot_claim("https://foo.blogspot.com/grant")
    )
    entry = RegisterEntry.objects.create(
        register="vgm_tr", external_key="1", name="A Blog", resolution="RESOLVED",
        organisation=body, last_seen=timezone.now(), contact_domain="blogspot.com",
    )
    partner = RegisterEntryPartner.objects.create(
        entry=entry, organisation=body, role="PARTNER", listed_name="A Blog",
        listed_identifier="9", listed_domain="blogspot.com", disposition="NEW",
    )
    kept = Organisation.objects.create(primary_domain="tum.de", name="TUM", kind="INSTITUTION")
    OrganisationDomain.objects.create(organisation=kept, registrable_domain="tum.de")

    out = StringIO()
    call_command("rederive_domains", stdout=out)

    assert not Organisation.objects.filter(id=body.id).exists()
    assert not OrganisationIdentifier.objects.filter(value="Q1").exists()
    award.refresh_from_db()
    entry.refresh_from_db()
    partner.refresh_from_db()
    assert award.organisation_id is None
    assert award.holder_domain == "foo.blogspot.com"
    assert entry.organisation_id is None and entry.resolution == "UNRESOLVED"
    assert entry.contact_domain == ""
    assert partner.organisation_id is None and partner.disposition == "NO_KEY"
    assert partner.listed_domain == ""
    assert Organisation.objects.filter(id=kept.id).exists()
    assert "unkeyed 1 merged organisations" in out.getvalue()


def test_a_second_run_changes_nothing() -> None:
    _merged_blog_body()
    call_command("rederive_domains", stdout=StringIO())
    out = StringIO()
    call_command("rederive_domains", stdout=out)
    assert "unkeyed 0 merged organisations" in out.getvalue()
    assert "re-derived 0 holder domains, 0 partner domains, 0 contact domains" in out.getvalue()
```

- [ ] **Step 2: Run them to verify they fail**

Run: `POSTGRES_DB=tehsil_provenance_gate uv run pytest tests/research/test_hosts.py tests/research/test_rederive_domains.py -q --create-db`
Expected: FAIL. `ImportError: cannot import name 'HOSTING_PLATFORMS'` and `Unknown command: 'rederive_domains'`.

- [ ] **Step 3: Implement**

Replace `apps/research/hosts.py`'s body below the module docstring, and append a paragraph to the docstring. The complete file:

```python
"""The registrable domain of a host -- the key every discovery route dedupes on.

One function, because getting it wrong is expensive in a specific way: a crude
"last two labels" rule reads `metu.edu.tr` as `edu.tr` and merges every Turkish
university into a single register row. `edu.tr`, `ac.uk` and `gov.az` are public
suffixes, and only the Public Suffix List knows that.

The suffix list is the snapshot bundled with tldextract, never fetched:
`suffix_list_urls=()` disables the live download, and a discovery sweep that
paused to refresh a suffix list would be making an unbudgeted outbound call
from inside a loop that is already rate-limited on other grounds.

**Private suffixes are on, and hosting platforms are suffixes too** (institution
provenance gate spec §5.6, 2026-09-26). With private suffixes off, one blog
anchored all of blogspot and one Russian university stood for all of edu.ru
(`tspu.edu.ru -> edu.ru`). The PSL's private section fixes github.io and
blogspot.com but not wordpress.com, weebly.com or sites.google.com, so the
platform list is passed as `extra_suffixes` as well (measured, tldextract
5.3.2). A platform's own root is then unkeyable (""), which is correct: it
names the landlord, never a publisher.
"""

from __future__ import annotations

from urllib.parse import urlsplit

import tldextract

#: Hosting platforms (spec §5.6). A body whose domain is one of these, or under
#: one, can be UNCONFIRMED and never RECOGNISED through its domain. 205 active
#: ROR records, 37 of them education, keep their website on such a platform
#: (wordpress.com 59, google.com 26, wixsite 23, weebly 20, blogspot 15).
#: Pinned by tests/research/test_hosts.py.
HOSTING_PLATFORMS: tuple[str, ...] = (
    "github.io", "gitlab.io", "blogspot.com", "wordpress.com", "wixsite.com",
    "weebly.com", "sites.google.com", "squarespace.com", "webflow.io",
    "netlify.app", "vercel.app", "pages.dev", "herokuapp.com",
    "firebaseapp.com", "web.app", "tumblr.com", "medium.com", "substack.com",
    "notion.site", "000webhostapp.com",
)

#: A label left of the registrable domain that marks user content rather than
#: the institution's own voice (spec §3). Any label counts: blogs.cs.tum.de is
#: a blog however deep it sits.
USER_CONTENT_LABELS = frozenset(
    {"blog", "blogs", "wiki", "forum", "forums", "people", "users", "sites",
     "student", "students"}
)

#: `suffix_list_urls=()` is the documented offline mode; `fallback_to_snapshot`
#: keeps the bundled list in play. Built once at import: the constructor reads
#: the snapshot, and building it per call would parse it per call.
_EXTRACT = tldextract.TLDExtract(
    suffix_list_urls=(),
    fallback_to_snapshot=True,
    include_psl_private_domains=True,
    extra_suffixes=HOSTING_PLATFORMS,
)


def registrable_domain(value: str) -> str:
    """The registrable domain of a host or URL, lowercased, or "" if there is none.

    "" is returned for an IP address, an unknown suffix, a hosting platform's
    own root and an empty input -- never a guess. A caller that cannot key a
    host must skip it, because a wrong key is a silently merged organisation
    rather than a visible failure.
    """
    text = value.strip()
    if not text:
        return ""
    host = urlsplit(text).hostname if "//" in text else text
    if not host:
        return ""
    # `registered_domain` is deprecated in tldextract 5.3; this is the same
    # value under the accurate name.
    return _EXTRACT(host.casefold()).top_domain_under_public_suffix


def is_hosting_platform(domain: str) -> bool:
    normalized = domain.casefold().strip(".")
    return any(
        normalized == platform or normalized.endswith(f".{platform}")
        for platform in HOSTING_PLATFORMS
    )


def is_institutional_url(url: str, domain: str) -> bool:
    """Whether `url` is the institution's own voice on `domain` (spec §3).

    On the domain's main host or an institutional subdomain; never a user
    subdomain, a `/~user` path, or a hosting platform.
    """
    parts = urlsplit(url)
    host = (parts.hostname or "").casefold()
    if not domain or is_hosting_platform(domain) or registrable_domain(host) != domain:
        return False
    labels = host[: -len(domain)].rstrip(".").split(".") if host != domain else []
    if any(label in USER_CONTENT_LABELS for label in labels):
        return False
    return not parts.path.startswith("/~")
```

Create `apps/research/management/commands/rederive_domains.py`:

```python
"""Re-key every stored registrable domain after the hosts.py fix (spec §5.6).

Operator-run once per database, idempotent, writes the catalogue (run with
DATABASE_ROLE=runtime_engine). A body keyed on a value that no longer keys to
itself -- `blogspot.com`, `github.io` -- merged unrelated publishers, and the
hosts that made it are not stored, so it cannot be split: it is deleted with
its identifiers, every link to it is cleared, and the next discovery run
re-records each publisher under its own key. No production database exists
(spec §5.6), so this touches developer and staging data only.

ponytail: a body merged under `google.com` (sites.google.com pages) still keys
to itself and is not detected; recreate such a dev database instead.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from django.core.management.base import BaseCommand
from django.db import models, transaction

from apps.funding.models import FundingOpportunity, FundingOpportunityEvidenceClaim
from apps.research.hosts import registrable_domain
from apps.research.models import (
    Organisation,
    OrganisationDomain,
    OrganisationIdentifier,
    RegisterEntry,
    RegisterEntryPartner,
)


def _stale(value: str) -> bool:
    return bool(value) and registrable_domain(value) != value


def merged_organisations() -> set[UUID]:
    ids = {
        organisation_id
        for organisation_id, value in OrganisationDomain.objects.values_list(
            "organisation_id", "registrable_domain"
        )
        if _stale(value)
    }
    ids |= {
        organisation_id
        for organisation_id, value in Organisation.objects.values_list("id", "primary_domain")
        if _stale(value)
    }
    return ids


@transaction.atomic
def unkey(organisation_id: UUID) -> None:
    FundingOpportunity.objects.filter(organisation_id=organisation_id).update(organisation=None)
    RegisterEntry.objects.filter(organisation_id=organisation_id).update(
        organisation=None, resolution=RegisterEntry.Resolution.UNRESOLVED
    )
    RegisterEntryPartner.objects.filter(organisation_id=organisation_id).update(
        organisation=None, disposition=RegisterEntryPartner.Disposition.NO_KEY
    )
    Organisation.objects.filter(parent_id=organisation_id).update(parent=None)
    OrganisationIdentifier.objects.filter(organisation_id=organisation_id).delete()
    OrganisationDomain.objects.filter(organisation_id=organisation_id).delete()
    Organisation.objects.filter(id=organisation_id).delete()


def rederive_holder_domains() -> int:
    """From the page the award was read on, when one is stored."""
    changed = 0
    rows = FundingOpportunity.objects.exclude(holder_domain="").values_list("id", "holder_domain")
    for opportunity_id, holder_domain in rows:
        final_url = (
            FundingOpportunityEvidenceClaim.objects.filter(
                opportunity_id=opportunity_id, evidence_claim__snapshot__isnull=False
            )
            .values_list("evidence_claim__snapshot__final_url", flat=True)
            .first()
        )
        new = registrable_domain(final_url) if final_url else registrable_domain(holder_domain)
        if new != holder_domain:
            FundingOpportunity.objects.filter(id=opportunity_id).update(holder_domain=new)
            changed += 1
    return changed


def rederive_column(model: type[models.Model], field: str) -> int:
    """For a column whose source URL is not stored: re-key the value itself."""
    changed = 0
    for row_id, value in model._default_manager.exclude(**{field: ""}).values_list("id", field):
        if _stale(value):
            model._default_manager.filter(id=row_id).update(**{field: registrable_domain(value)})
            changed += 1
    return changed


class Command(BaseCommand):
    help = (
        "Re-key stored registrable domains after the private-suffix fix (spec §5.6). "
        "Writes the catalogue: run with DATABASE_ROLE=runtime_engine."
    )

    def handle(self, *args: Any, **options: Any) -> None:
        merged = merged_organisations()
        for organisation_id in sorted(merged):
            unkey(organisation_id)
        holders = rederive_holder_domains()
        partners = rederive_column(RegisterEntryPartner, "listed_domain")
        contacts = rederive_column(RegisterEntry, "contact_domain")
        self.stdout.write(
            f"unkeyed {len(merged)} merged organisations; re-derived {holders} holder "
            f"domains, {partners} partner domains, {contacts} contact domains"
        )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `POSTGRES_DB=tehsil_provenance_gate uv run pytest tests/research/test_hosts.py tests/research/test_rederive_domains.py -q`
Expected: PASS.

- [ ] **Step 5: Run the four checks** (Global Constraints). Every existing registrable-domain caller now uses the new key. If a test elsewhere asserted the old platform-root key, read it before changing it: the old key was the bug.

- [ ] **Step 6: Commit**

```bash
git -C /home/orkhan/Desktop/provenance-gate add apps/research/hosts.py apps/research/management/commands/rederive_domains.py tests/research/test_hosts.py tests/research/test_rederive_domains.py
git -C /home/orkhan/Desktop/provenance-gate commit -m "fix(research): private suffixes and hosting platforms key their tenants; rederive_domains"
```

---

### Task 2: Storage, grants, wording and the rollout setting

**Files:**
- Modify: `apps/research/models.py`, `apps/funding/models.py`, `apps/audit/redaction.py`, `config/settings/base.py`
- Create: `apps/research/provenance.py`, `apps/research/migrations/0011_provenance.py` (generated, then RLS appended), `apps/funding/migrations/0051_provenance.py` (generated), `tests/research/provenance_helpers.py`
- Test: `tests/research/test_provenance_storage.py`

**Interfaces:**
- Consumes: `apps.research.models.Organisation`.
- Produces:
  - `research.ProvenanceVerdict`:
    - `organisation` (OneToOne, pk, `related_name="provenance"`)
    - `verdict`, `reason_code`, `bound_domain`, `evidence` (JSON)
    - `checked_at`, `next_check_at`, `first_bound_at`
    - Nested `ProvenanceVerdict.Verdict` / `ProvenanceVerdict.Reason` TextChoices
  - `research.ProvenanceVerdictChange` (`organisation`, `old`, `new`, `reason_code`, `at`)
  - New `RegisterEntry` fields: `website_domain`, `origin_verified_domain`, `origin_verified_at`
  - New `ClosedList` field: `loaded_at`
  - New `Program` fields: `evidence_domain: str`, `evidence_institutional: bool`
  - `RecommendationRun.pending_bodies: list[UUID]`
  - `PackVersion.change_notes: list[dict]`
  - `RecommendationCandidate.provenance_reason_code: str`, `RecommendationCandidate.provenance_body_id: UUID | None`
  - `apps.research.provenance`:
    - `Verdict`, `Reason`
    - `RECOGNISED_REASONS`, `UNCONFIRMED_REASONS`, `BLOCKED_REASONS`, `WAITING_REASONS: frozenset[str]`
    - `verdict_of(reason_code: str) -> str`
    - `WORDING: dict[str, tuple[str, str]]` (en, az)
    - `recognition_note(reason_code: str) -> str`
    - `record_verdict(organisation, *, verdict: str, reason_code: str, bound_domain: str, evidence: dict[str, object], now: datetime, next_check_at: datetime | None) -> ProvenanceVerdict`
  - Settings: `PROVENANCE_GATE_ENFORCED: bool` (default False), `PROVENANCE_CYCLE_DAYS: int` (30)
  - `tests/research/provenance_helpers.py`: `make_body(domain, *, kind="INSTITUTION", country_code="") -> Organisation`, `make_list(slug, **kw) -> ClosedList`, `page(url, html, *, final_url=None, outcome=Outcome.FETCHED) -> FetchedPage`, `FakeFetch(pages)`, `FakeStore(objects)`

- [ ] **Step 1: Write the failing tests**

Create `tests/research/provenance_helpers.py`:

```python
"""Builders shared by the provenance-gate tests. Catalogue rows only; no network."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date

from apps.research.fetch.types import FetchedPage, Outcome
from apps.research.models import ClosedList, Organisation
from apps.research.register import record_organisation


def make_body(domain: str, *, kind: str = "INSTITUTION", country_code: str = "") -> Organisation:
    return record_organisation(
        domain=domain, name=domain, kind=kind, country_code=country_code, found_via="TEST"
    )


def make_list(
    slug: str,
    *,
    country_code: str = "",
    terms: str = "OPEN",
    printed_size: int | None = None,
    source_url: str = "https://register.example.test/list",
    holder_kinds: tuple[str, ...] = ("INSTITUTION",),
) -> ClosedList:
    return ClosedList.objects.create(
        slug=slug, title=slug, country_code=country_code, holder_kinds=list(holder_kinds),
        rung=1, source_url=source_url, maintainer="test", carries_purpose=False,
        carries_website=True, reuse_terms=terms, is_denominator=True,
        read_policy="ENUMERATE_ONLY", printed_size=printed_size,
        verified_on=date(2026, 9, 26),
    )


def page(
    url: str,
    html: str | bytes,
    *,
    final_url: str | None = None,
    outcome: Outcome = Outcome.FETCHED,
    content_type: str = "text/html",
) -> FetchedPage:
    body = html.encode() if isinstance(html, str) else html
    return FetchedPage(
        final_url=final_url or url, redirects=(), content_type=content_type, body=body,
        fetched_via="FIRECRAWL", outcome=outcome,
    )


@dataclass
class FakeFetch:
    """`fetch_page` stand-in: a URL it does not hold answers DEAD, bodiless."""

    pages: Mapping[str, FetchedPage]
    calls: list[str] = field(default_factory=list)

    def __call__(self, url: str, **_kwargs: object) -> FetchedPage:
        self.calls.append(url)
        return self.pages.get(url) or page(url, b"", outcome=Outcome.DEAD)


@dataclass
class FakeStore:
    objects: dict[str, bytes] = field(default_factory=dict)

    def put(self, key: str, body: bytes) -> str:
        self.objects[key] = body
        return "test-version"

    def get(self, key: str) -> bytes:
        return self.objects[key]
```

Create `tests/research/test_provenance_storage.py`:

```python
"""The verdict tables: shape, grants, the one writer and the wording (spec §8)."""

from datetime import timedelta

import pytest
from django.conf import settings
from django.db import IntegrityError
from django.utils import timezone

from apps.research.models import ProvenanceVerdict, ProvenanceVerdictChange
from apps.research.provenance import (
    BLOCKED_REASONS,
    RECOGNISED_REASONS,
    UNCONFIRMED_REASONS,
    WORDING,
    Reason,
    Verdict,
    recognition_note,
    record_verdict,
    verdict_of,
)
from tests.conftest import catalogue_tables
from tests.research.provenance_helpers import make_body

pytestmark = pytest.mark.django_db


def test_the_reason_enum_is_spec_4_1_and_partitions_into_three_verdicts() -> None:
    assert set(Reason.values) == RECOGNISED_REASONS | UNCONFIRMED_REASONS | BLOCKED_REASONS
    assert RECOGNISED_REASONS == {
        "register", "curated_list", "funder_list", "vouched_by_link", "government_zone",
    }
    assert BLOCKED_REASONS == {
        "mill_list", "accreditation_mill", "fee_to_release_award", "degree_for_payment",
    }
    assert UNCONFIRMED_REASONS == {
        "not_evaluated", "register_not_loaded", "absent_from_register", "no_domain_binding",
        "unmapped_list_row", "domain_registered_after_listing", "veto_conflict",
        "evidence_off_domain", "lookup_failed", "no_holder_body", "vouch_link_missing",
    }
    assert verdict_of("register") == Verdict.RECOGNISED
    assert verdict_of("mill_list") == Verdict.BLOCKED
    assert verdict_of("lookup_failed") == Verdict.UNCONFIRMED


def test_every_reason_has_fixed_wording_in_english_and_azerbaijani() -> None:
    assert set(WORDING) == set(Reason.values)
    for english, azerbaijani in WORDING.values():
        assert english.strip() and azerbaijani.strip()
        assert english != azerbaijani


def test_the_note_is_shown_for_unconfirmed_only() -> None:
    assert recognition_note("absent_from_register").startswith("Recognition not confirmed: ")
    assert recognition_note("register") == ""
    assert recognition_note("mill_list") == ""
    assert recognition_note("") == ""


def test_a_verdict_whose_reason_belongs_to_another_verdict_is_refused() -> None:
    body = make_body("tum.de")
    with pytest.raises(IntegrityError):
        ProvenanceVerdict.objects.create(
            organisation=body, verdict="RECOGNISED", reason_code="mill_list",
            checked_at=timezone.now(),
        )


def test_record_verdict_refuses_a_mismatched_pair_before_the_database() -> None:
    with pytest.raises(ValueError, match="not a RECOGNISED reason"):
        record_verdict(
            make_body("tum.de"), verdict="RECOGNISED", reason_code="lookup_failed",
            bound_domain="tum.de", evidence={}, now=timezone.now(), next_check_at=None,
        )


def test_each_transition_writes_one_change_row() -> None:
    body = make_body("tum.de")
    now = timezone.now()
    record_verdict(body, verdict="UNCONFIRMED", reason_code="not_evaluated",
                   bound_domain="tum.de", evidence={}, now=now, next_check_at=now)
    record_verdict(body, verdict="RECOGNISED", reason_code="register", bound_domain="tum.de",
                   evidence={"source_slug": "x"}, now=now, next_check_at=None)
    changes = list(ProvenanceVerdictChange.objects.filter(organisation=body).order_by("at", "new"))
    assert [(c.old, c.new, c.reason_code) for c in changes] == [
        ("", "UNCONFIRMED", "not_evaluated"),
        ("UNCONFIRMED", "RECOGNISED", "register"),
    ]


def test_an_unchanged_verdict_writes_no_second_change_row() -> None:
    body = make_body("tum.de")
    now = timezone.now()
    for _ in range(2):
        record_verdict(body, verdict="RECOGNISED", reason_code="register",
                       bound_domain="tum.de", evidence={}, now=now, next_check_at=None)
    assert ProvenanceVerdictChange.objects.filter(organisation=body).count() == 1


def test_first_bound_at_is_kept_through_a_recheck_and_a_downgrade() -> None:
    body = make_body("esmt.berlin")
    first = timezone.now() - timedelta(days=400)
    record_verdict(body, verdict="RECOGNISED", reason_code="register",
                   bound_domain="esmt.berlin", evidence={}, now=first, next_check_at=None)
    record_verdict(body, verdict="RECOGNISED", reason_code="register",
                   bound_domain="esmt.berlin", evidence={}, now=timezone.now(), next_check_at=None)
    record_verdict(body, verdict="UNCONFIRMED", reason_code="domain_registered_after_listing",
                   bound_domain="esmt.berlin", evidence={}, now=timezone.now(), next_check_at=None)
    assert ProvenanceVerdict.objects.get(organisation=body).first_bound_at == first


def test_a_new_bound_domain_restarts_first_bound_at() -> None:
    body = make_body("nyenrode.nl")
    old = timezone.now() - timedelta(days=30)
    record_verdict(body, verdict="RECOGNISED", reason_code="curated_list",
                   bound_domain="nyenrode.com", evidence={}, now=old, next_check_at=None)
    now = timezone.now()
    record_verdict(body, verdict="RECOGNISED", reason_code="curated_list",
                   bound_domain="nyenrode.nl", evidence={}, now=now, next_check_at=None)
    assert ProvenanceVerdict.objects.get(organisation=body).first_bound_at == now


def test_both_tables_are_catalogue_tables(db_cursor) -> None:
    """test_catalog_grants.py then asserts, as the roles themselves, that
    runtime_web holds nothing on them and runtime_engine holds DML."""
    tables = set(catalogue_tables(db_cursor))
    assert {"research_provenanceverdict", "research_provenanceverdictchange"} <= tables


@pytest.mark.django_db(transaction=True)
def test_the_engine_role_writes_a_verdict_and_the_web_role_cannot_read_one(
    role_connection,
) -> None:
    import psycopg

    body = make_body("tum.de")
    with role_connection("runtime_engine") as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO research_provenanceverdict (organisation_id, verdict, reason_code, "
            "bound_domain, evidence, checked_at) VALUES (%s, 'UNCONFIRMED', 'not_evaluated', "
            "'tum.de', '{}', now())",
            [body.id],
        )
        cur.execute(
            "INSERT INTO research_provenanceverdictchange (id, organisation_id, old, new, "
            "reason_code, at) VALUES (gen_random_uuid(), %s, '', 'UNCONFIRMED', "
            "'not_evaluated', now())",
            [body.id],
        )
    with role_connection("runtime_web") as conn, conn.cursor() as cur:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            cur.execute("SELECT 1 FROM research_provenanceverdict")


def test_the_gate_ships_off_and_a_cycle_is_thirty_days() -> None:
    assert settings.PROVENANCE_GATE_ENFORCED is False
    assert settings.PROVENANCE_CYCLE_DAYS == 30
```

- [ ] **Step 2: Run them to verify they fail**

Run: `POSTGRES_DB=tehsil_provenance_gate uv run pytest tests/research/test_provenance_storage.py -q --create-db`
Expected: FAIL with `ImportError: cannot import name 'ProvenanceVerdict'`.

- [ ] **Step 3: Implement the models**

In `apps/research/models.py`, add these fields to `ClosedList` (after `verified_on`):

```python
    #: When code last read this list into RegisterEntry rows (a register loader,
    #: spec §5.1). Null for a list only ever read by hand or never loaded; a
    #: body in a country whose register has no `loaded_at` is
    #: UNCONFIRMED(register_not_loaded), never absent from it.
    loaded_at = models.DateTimeField(null=True, blank=True)
```

Add these fields to `RegisterEntry` (after `read_state_at`):

```python
    #: The registrable domain of the website the list printed for this row --
    #: the domain `record_list` bound it by, and a verdict's `bound_domain`.
    website_domain = models.CharField(max_length=253, blank=True, default="")
    #: A reviewed row's website counts as evidence only once its origin was
    #: fetched and named the institution (spec §13.8, `verify_list_origins`).
    #: Equal to `website_domain` when verified; a changed website voids it.
    origin_verified_domain = models.CharField(max_length=253, blank=True, default="")
    origin_verified_at = models.DateTimeField(null=True, blank=True)
```

Append at the end of `apps/research/models.py`:

```python
_RECOGNISED_REASONS = (
    "register", "curated_list", "funder_list", "vouched_by_link", "government_zone",
)
_UNCONFIRMED_REASONS = (
    "not_evaluated", "register_not_loaded", "absent_from_register", "no_domain_binding",
    "unmapped_list_row", "domain_registered_after_listing", "veto_conflict",
    "evidence_off_domain", "lookup_failed", "no_holder_body", "vouch_link_missing",
)
_BLOCKED_REASONS = (
    "mill_list", "accreditation_mill", "fee_to_release_award", "degree_for_payment",
)


class ProvenanceVerdict(models.Model):
    """Whether a body may reach a student (institution provenance gate spec §4, §8).

    Shared catalogue: every tenant reads it, only `runtime_engine` writes it
    (research/0011's RLS block), `runtime_web` holds no grant. No row means
    `not_evaluated` -- the table starts empty and the absence is read that way
    everywhere (spec §7.7). Written only by `apps.research.provenance.record_verdict`.
    """

    class Verdict(models.TextChoices):
        RECOGNISED = "RECOGNISED"
        UNCONFIRMED = "UNCONFIRMED"
        BLOCKED = "BLOCKED"

    class Reason(models.TextChoices):
        REGISTER = "register"
        CURATED_LIST = "curated_list"
        FUNDER_LIST = "funder_list"
        VOUCHED_BY_LINK = "vouched_by_link"
        GOVERNMENT_ZONE = "government_zone"
        NOT_EVALUATED = "not_evaluated"
        REGISTER_NOT_LOADED = "register_not_loaded"
        ABSENT_FROM_REGISTER = "absent_from_register"
        NO_DOMAIN_BINDING = "no_domain_binding"
        UNMAPPED_LIST_ROW = "unmapped_list_row"
        DOMAIN_REGISTERED_AFTER_LISTING = "domain_registered_after_listing"
        VETO_CONFLICT = "veto_conflict"
        EVIDENCE_OFF_DOMAIN = "evidence_off_domain"
        LOOKUP_FAILED = "lookup_failed"
        NO_HOLDER_BODY = "no_holder_body"
        VOUCH_LINK_MISSING = "vouch_link_missing"
        MILL_LIST = "mill_list"
        ACCREDITATION_MILL = "accreditation_mill"
        FEE_TO_RELEASE_AWARD = "fee_to_release_award"
        DEGREE_FOR_PAYMENT = "degree_for_payment"

    organisation = models.OneToOneField(
        Organisation, on_delete=models.CASCADE, primary_key=True, related_name="provenance"
    )
    verdict = models.CharField(max_length=12, choices=Verdict.choices)
    reason_code = models.CharField(max_length=32, choices=Reason.choices)
    #: The domain the recognising evidence binds (spec §5.2); for a verdict that
    #: is not RECOGNISED, the body's own domain. The pool joins programmes on it.
    bound_domain = models.CharField(max_length=253, blank=True, default="")
    #: source_slug, source_url, list_date, identifier {scheme, value}, vouch_url,
    #: admitted_via, rdap {status, date, detail}, content_checks, mill, content_hits.
    evidence = models.JSONField(default=dict, blank=True)
    checked_at = models.DateTimeField()
    #: Null for BLOCKED, which is never retried.
    next_check_at = models.DateTimeField(null=True, blank=True)
    #: When OUR records first saw `bound_domain` bound to this body -- the only
    #: date a registration date can be compared with (spec §5.5).
    first_bound_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=("verdict", "bound_domain"), name="provenance_bound_idx"),
            models.Index(fields=("next_check_at",), name="provenance_due_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(verdict="RECOGNISED", reason_code__in=_RECOGNISED_REASONS)
                    | Q(verdict="UNCONFIRMED", reason_code__in=_UNCONFIRMED_REASONS)
                    | Q(verdict="BLOCKED", reason_code__in=_BLOCKED_REASONS)
                ),
                name="provenance_verdict_reason_shape",
            ),
        ]


class ProvenanceVerdictChange(models.Model):
    """Append-only history of verdicts (spec §8): drives pack notes and shows a
    body whose verdict keeps flipping."""

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    organisation = models.ForeignKey(
        Organisation, on_delete=models.CASCADE, related_name="provenance_changes"
    )
    #: "" for the first verdict a body ever got.
    old = models.CharField(max_length=12, blank=True, default="")
    new = models.CharField(max_length=12, choices=ProvenanceVerdict.Verdict.choices)
    reason_code = models.CharField(max_length=32, choices=ProvenanceVerdict.Reason.choices)
    at = models.DateTimeField()

    class Meta:
        indexes = [models.Index(fields=("organisation", "-at"), name="provenance_change_idx")]
```

In `apps/funding/models.py`, add to `Program` (after `provider_text`):

```python
    #: The single registrable domain every OfficialEvidenceClaim of this programme
    #: sits on, or "" when they disagree or there are none (institution
    #: provenance gate spec §3). Written from the evidence URLs by the catalogue
    #: writer, never from the page's name; the pool joins it to a RECOGNISED
    #: body's `bound_domain`. db_default for raw-SQL catalogue writers.
    evidence_domain = models.CharField(
        max_length=253, blank=True, default="", db_default="", db_index=True
    )
    #: Whether every evidence URL is on that domain's main host or an
    #: institutional subdomain -- no blog, wiki, forum, ~user path or platform.
    evidence_institutional = models.BooleanField(default=False, db_default=False)
```

Add to `RecommendationRun` (after `dispatched_at`):

```python
    #: Bodies this run's pack left out because their verdict was not computed
    #: yet (spec §7.1). The sweep re-runs the student when one resolves
    #: RECOGNISED. Organisation ids, deliberately not a foreign key into the
    #: catalogue.
    pending_bodies = ArrayField(models.UUIDField(), default=list, blank=True)
```

Add to `PackVersion` (after `approved_version_id`):

```python
    #: What changed in this version because a body's verdict changed (spec §7.3):
    #: [{"candidate_name", "reason_code", "action": "removed" | "kept", "at"}].
    change_notes = models.JSONField(default=list, blank=True)
```

Add to `RecommendationCandidate` (after `evidence_confidence`):

```python
    #: Tenant copies of the body's provenance verdict (spec §8), written by the
    #: worker: the web tier renders from these and never reads the catalogue.
    #: "" means not checked yet. No choices: research.models owns the enum and
    #: funding must not import it.
    provenance_reason_code = models.CharField(max_length=32, blank=True, default="")
    provenance_body_id = models.UUIDField(null=True, blank=True)
```

- [ ] **Step 4: Generate the migrations and append the RLS block**

Run:
```bash
cd /home/orkhan/Desktop/provenance-gate
ls apps/research/migrations apps/funding/migrations | tail -5
uv run python manage.py makemigrations research --name provenance
uv run python manage.py makemigrations funding --name provenance
```
Expected: `apps/research/migrations/0011_provenance.py` (depends only on `("research", "0010_closed_lists")`) and `apps/funding/migrations/0051_provenance.py`. If the research migration lists a funding dependency, remove it. Research never depends on funding.

Edit `apps/research/migrations/0011_provenance.py`. Insert this after the imports:

```python
# The CLAUDE.md recipe for a new catalogue table, as research/0010 applies it:
# every tenant reads, only `runtime_engine` writes, and `runtime_web` holds no
# table grant at all (the catalogue boundary is a GRANT, not a policy). Neither
# table owns a sequence (UUID and one-to-one primary keys). Research cannot
# depend on funding, so the roles are ensured here exactly as 0010 does.
_TABLES = ("research_provenanceverdict", "research_provenanceverdictchange")

_ENSURE_ROLES = """
DO $$ BEGIN
    IF (SELECT count(*) FROM pg_roles
         WHERE rolname IN ('runtime_engine', 'runtime_web')) < 2
       AND NOT (SELECT rolsuper FROM pg_roles WHERE rolname = current_user) THEN
        RAISE EXCEPTION 'runtime_engine / runtime_web do not both exist: run '
            'scripts/create_runtime_role.sql as the admin role, then re-run the migration';
    END IF;
END $$;
""" + "".join(
    f"""
DO $$ BEGIN
    CREATE ROLE {role} NOLOGIN;
EXCEPTION WHEN duplicate_object OR unique_violation THEN NULL;
END $$;
"""
    for role in ("runtime_engine", "runtime_web")
)

RLS_SQL = _ENSURE_ROLES + "".join(
    f"""
ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY;
CREATE POLICY shared_catalog_select ON public.{table}
    FOR SELECT USING (true);
CREATE POLICY runtime_engine_write ON public.{table}
    FOR ALL TO runtime_engine USING (true) WITH CHECK (true);
GRANT SELECT, INSERT, UPDATE, DELETE ON public.{table} TO runtime_engine;
REVOKE ALL ON public.{table} FROM runtime_web;
"""
    for table in _TABLES
)

REVERSE_RLS_SQL = "".join(
    f"""
DROP POLICY IF EXISTS runtime_engine_write ON public.{table};
DROP POLICY IF EXISTS shared_catalog_select ON public.{table};
ALTER TABLE public.{table} DISABLE ROW LEVEL SECURITY;
"""
    for table in _TABLES
)
```

Then append as the last element of `operations`:

```python
        migrations.RunSQL(RLS_SQL, reverse_sql=REVERSE_RLS_SQL),
```

Do not add `FORCE ROW LEVEL SECURITY`. Checked on this branch: the catalogue tables in research/0007 and 0010 do not carry it; only tenant tables do (research/0002, funding/0002). The recipe is 0010's, exactly.

- [ ] **Step 5: Implement `apps/research/provenance.py`, redaction and settings**

Create `apps/research/provenance.py`:

```python
"""Institution provenance: the verdict vocabulary and its one writer.

Spec: docs/superpowers/specs/2026-09-26-institution-provenance-gate-design.md
§4 (verdicts), §8 (storage). Admission rests only on evidence the attacker
cannot write; content checks may only veto; absence is never BLOCKED.
"""

from __future__ import annotations

from datetime import datetime

from django.db import transaction

from .models import (
    _BLOCKED_REASONS,
    _RECOGNISED_REASONS,
    _UNCONFIRMED_REASONS,
    Organisation,
    ProvenanceVerdict,
    ProvenanceVerdictChange,
)

Verdict = ProvenanceVerdict.Verdict
Reason = ProvenanceVerdict.Reason

RECOGNISED_REASONS: frozenset[str] = frozenset(_RECOGNISED_REASONS)
UNCONFIRMED_REASONS: frozenset[str] = frozenset(_UNCONFIRMED_REASONS)
BLOCKED_REASONS: frozenset[str] = frozenset(_BLOCKED_REASONS)
#: A pack build leaves these out and queues them rather than excluding them for
#: a reason (spec §7.1): the check has simply not happened yet.
WAITING_REASONS: frozenset[str] = frozenset({Reason.NOT_EVALUATED, Reason.REGISTER_NOT_LOADED})


def verdict_of(reason_code: str) -> str:
    if reason_code in RECOGNISED_REASONS:
        return Verdict.RECOGNISED
    if reason_code in BLOCKED_REASONS:
        return Verdict.BLOCKED
    return Verdict.UNCONFIRMED


#: Fixed wording per reason, English then Azerbaijani (spec §4.1, §9.4).
#: Pinned by tests/research/test_provenance_storage.py.
WORDING: dict[str, tuple[str, str]] = {
    Reason.REGISTER: (
        "Named on its country's official register of recognised institutions.",
        "Ölkəsinin tanınmış ali təhsil müəssisələrinin rəsmi reyestrində göstərilib.",
    ),
    Reason.CURATED_LIST: (
        "Named on a reviewed official list.",
        "Yoxlanılmış rəsmi siyahıda göstərilib.",
    ),
    Reason.FUNDER_LIST: (
        "Named by a scholarship funder's own list of institutions.",
        "Təqaüd verən qurumun öz müəssisələr siyahısında göstərilib.",
    ),
    Reason.VOUCHED_BY_LINK: (
        "Shown as part of a recognised institution on that institution's own website.",
        "Tanınmış müəssisənin öz saytında onun tərkib hissəsi kimi göstərilib.",
    ),
    Reason.GOVERNMENT_ZONE: (
        "A government body, on a domain only governments can hold.",
        "Yalnız dövlət qurumlarına verilən domendə yerləşən dövlət qurumudur.",
    ),
    Reason.NOT_EVALUATED: ("Not checked yet.", "Hələ yoxlanılmayıb."),
    Reason.REGISTER_NOT_LOADED: (
        "Its country's register has not been read yet.",
        "Ölkəsinin reyestri hələ oxunmayıb.",
    ),
    Reason.ABSENT_FROM_REGISTER: (
        "Not found on its country's register; this alone is not proof of a problem.",
        "Ölkəsinin reyestrində tapılmadı; bu, tək başına problem olduğunu sübut etmir.",
    ),
    Reason.NO_DOMAIN_BINDING: (
        "Its website could not yet be tied to an official record.",
        "Saytı hələ rəsmi qeydlə əlaqələndirilə bilmədi.",
    ),
    Reason.UNMAPPED_LIST_ROW: (
        "Listed officially, but its website is not confirmed yet.",
        "Rəsmi siyahıdadır, lakin saytı hələ təsdiqlənməyib.",
    ),
    Reason.DOMAIN_REGISTERED_AFTER_LISTING: (
        "Its web address was registered again after it was listed; we are re-checking.",
        "Sayt ünvanı siyahıya salındıqdan sonra yenidən qeydiyyatdan keçib; yenidən yoxlayırıq.",
    ),
    Reason.VETO_CONFLICT: (
        "Recognised, but its pages carry wording we must check by hand.",
        "Tanınır, lakin səhifələrində əl ilə yoxlanmalı ifadələr var.",
    ),
    Reason.EVIDENCE_OFF_DOMAIN: (
        "The programme's pages are not on the institution's own website.",
        "Proqramın səhifələri müəssisənin öz saytında deyil.",
    ),
    Reason.LOOKUP_FAILED: (
        "An official source could not be reached; we will try again.",
        "Rəsmi mənbəyə çatmaq mümkün olmadı; yenidən cəhd edəcəyik.",
    ),
    Reason.NO_HOLDER_BODY: (
        "The award does not name the body that pays it.",
        "Təqaüd onu ödəyən qurumu göstərmir.",
    ),
    Reason.VOUCH_LINK_MISSING: (
        "The recognised institution no longer links to it; we are re-checking.",
        "Tanınmış müəssisə artıq ona keçid vermir; yenidən yoxlayırıq.",
    ),
    Reason.MILL_LIST: (
        "On a published list of unaccredited institutions.",
        "Akkreditasiyasız müəssisələrin dərc olunmuş siyahısındadır.",
    ),
    Reason.ACCREDITATION_MILL: (
        "Claims accreditation from a known fake accreditor.",
        "Tanınmış saxta akkreditasiya qurumunun akkreditasiyasını iddia edir.",
    ),
    Reason.FEE_TO_RELEASE_AWARD: (
        "Asks for a fee to release a scholarship.",
        "Təqaüdü vermək üçün ödəniş tələb edir.",
    ),
    Reason.DEGREE_FOR_PAYMENT: (
        "Offers a degree for payment without study.",
        "Təhsil almadan ödənişlə diplom təklif edir.",
    ),
}


def recognition_note(reason_code: str) -> str:
    """What a student reads beside a programme whose recognition is not
    confirmed (owner decision, spec preamble); "" for any other code."""
    if not reason_code or verdict_of(reason_code) != Verdict.UNCONFIRMED:
        return ""
    return f"Recognition not confirmed: {WORDING[reason_code][0]}"


@transaction.atomic
def record_verdict(
    organisation: Organisation,
    *,
    verdict: str,
    reason_code: str,
    bound_domain: str,
    evidence: dict[str, object],
    now: datetime,
    next_check_at: datetime | None,
) -> ProvenanceVerdict:
    """Write a body's verdict and, when it changed, one history row.

    `first_bound_at` is set when a RECOGNISED verdict first binds a domain and
    survives re-checks and downgrades of that same domain, because it is the
    date a later registration date is compared with (spec §5.5).
    """
    if verdict_of(reason_code) != verdict:
        raise ValueError(f"{reason_code} is not a {verdict} reason")
    current = ProvenanceVerdict.objects.select_for_update().filter(organisation=organisation).first()
    if verdict == Verdict.RECOGNISED:
        keeps = (
            current is not None
            and current.first_bound_at is not None
            and current.bound_domain == bound_domain
        )
        first_bound_at = current.first_bound_at if keeps and current else now
    else:
        first_bound_at = current.first_bound_at if current is not None else None
    row, _created = ProvenanceVerdict.objects.update_or_create(
        organisation=organisation,
        defaults={
            "verdict": verdict,
            "reason_code": reason_code,
            "bound_domain": bound_domain,
            "evidence": evidence,
            "checked_at": now,
            "next_check_at": next_check_at,
            "first_bound_at": first_bound_at,
        },
    )
    if current is None or (current.verdict, current.reason_code) != (verdict, reason_code):
        ProvenanceVerdictChange.objects.create(
            organisation=organisation,
            old=current.verdict if current is not None else "",
            new=verdict,
            reason_code=reason_code,
            at=now,
        )
    return row
```

In `apps/audit/redaction.py`, extend three `KEEP` tuples.

- `"funding.PackVersion"` gains `"change_notes",`. Put this comment above it: `# change_notes names programmes and a reason code, never a person.`
- `"funding.RecommendationCandidate"` gains `"provenance_reason_code", "provenance_body_id",`. Comment: `# provenance_*: a fact about the institution, not the student.`
- `"funding.RecommendationRun"` becomes `("state", "created_at", "dispatched_at", "pending_bodies")`. Comment: `# pending_bodies: catalogue organisation ids, not about the student.`

In `config/settings/base.py`, after `ROR_CLIENT_ID`:

```python
#: The institution provenance gate (2026-09-26 spec §7.7). OFF until
#: `manage.py provenance_check --all` has filled the verdict table: enforced on
#: an empty table, every pack is empty. docs/runbooks/deploy.md has the order.
PROVENANCE_GATE_ENFORCED = os.getenv("PROVENANCE_GATE_ENFORCED", "") == "1"
#: One re-check cycle: register reloads, RECOGNISED re-checks and the sweep's
#: two-cycle removal all count in these.
PROVENANCE_CYCLE_DAYS = int(os.getenv("PROVENANCE_CYCLE_DAYS", "30"))
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `POSTGRES_DB=tehsil_provenance_gate uv run pytest tests/research/test_provenance_storage.py tests/tenancy/test_catalog_grants.py tests/audit/test_redaction_classification.py -q --create-db`
Expected: PASS. `test_catalog_grants.py` now covers the two new tables automatically, and it fails if the `REVOKE` is missing.

- [ ] **Step 7: Run the four checks.**

- [ ] **Step 8: Commit**

```bash
git -C /home/orkhan/Desktop/provenance-gate add apps/research/models.py apps/research/provenance.py apps/research/migrations/0011_provenance.py apps/funding/models.py apps/funding/migrations/0051_provenance.py apps/audit/redaction.py config/settings/base.py tests/research/provenance_helpers.py tests/research/test_provenance_storage.py
git -C /home/orkhan/Desktop/provenance-gate commit -m "feat(research): provenance verdict tables, grants, wording and the rollout setting"
```

---

### Task 3: Each programme's evidence domain, written by the catalogue writer

**Files:**
- Modify: `apps/research/provenance.py`, `apps/research/catalog.py:497-513`, `tests/research/provenance_helpers.py`
- Test: `tests/research/test_program_evidence.py`

**Interfaces:**
- Consumes:
  - `hosts.registrable_domain`, `hosts.is_institutional_url`, `hosts.is_hosting_platform`
  - `register.record_organisation`
- Produces:
  - `apps.research.provenance.evidence_of(urls: Iterable[str]) -> tuple[str, bool]`
  - `write_catalog_entry` now sets `Program.evidence_domain` / `evidence_institutional`, and records an `Organisation` (kind `INSTITUTION`, found_via `CATALOG:programme`, no country) for the evidence domain.
  - `tests.research.provenance_helpers.evidence_program(*urls: str, name: str = "MSc Computer Science", institution: Institution | None = None) -> Program`

- [ ] **Step 1: Write the failing tests**

Add to `tests/research/provenance_helpers.py`. The new imports go at the top of the file, with the existing ones; ruff's E402 rejects imports placed mid-file:

```python
from urllib.parse import urlsplit
from uuid import uuid4

from django.utils import timezone

from apps.funding.models import (
    Institution,
    OfficialEvidenceClaim,
    OfficialSource,
    Program,
    ProgramEvidenceClaim,
)
from apps.research.provenance import evidence_of


def evidence_program(
    *urls: str, name: str = "MSc Computer Science", institution: Institution | None = None
) -> Program:
    """A programme whose OfficialEvidenceClaims sit on `urls`, with its evidence
    columns set the way the catalogue writer sets them."""
    institution = institution or Institution.objects.create(
        canonical_key=f"institution:{uuid4()}", name="Example University",
        country_code="DE", official_website="https://university.example.test/",
    )
    program = Program.objects.create(
        institution=institution, canonical_key=f"program:{uuid4()}", name=name,
        campus_name="Main", city="Munich", country_code="DE", location_key=f"de:{uuid4()}",
        degree_level="MASTER", teaching_languages=["English"], duration_months=24,
    )
    for url in urls:
        source, _ = OfficialSource.objects.get_or_create(
            canonical_url=url,
            defaults={"publisher": urlsplit(url).hostname or url, "source_type": "PROGRAM"},
        )
        claim = OfficialEvidenceClaim.objects.create(
            source=source, claim=f"{name} is offered", evidence_strength="DIRECT",
            visibility="STUDENT_FACING", claim_class="IDENTITY", last_checked_at=timezone.now(),
        )
        ProgramEvidenceClaim.objects.create(program=program, evidence_claim=claim)
    domain, institutional = evidence_of(urls)
    Program.objects.filter(id=program.id).update(
        evidence_domain=domain, evidence_institutional=institutional
    )
    program.refresh_from_db()
    return program
```

Create `tests/research/test_program_evidence.py`:

```python
"""A programme is judged by its own evidence, never by its Institution row (spec §3)."""

import pytest
from django.utils import timezone

from apps.funding.models import Institution, OfficialSource, OfficialSourceSnapshot
from apps.research.catalog import write_catalog_entry
from apps.research.discovery import LeadIdentity, ResearchLead
from apps.research.extraction import ExtractedClaims, TeachingLanguageClaim
from apps.research.models import OrganisationDomain
from apps.research.provenance import evidence_of

pytestmark = pytest.mark.django_db

CLAIMS = ExtractedClaims(
    duration_months=24,
    teaching_languages=(TeachingLanguageClaim(language="English", evidence="Taught in English."),),
    confidence=0.9,
)


@pytest.mark.parametrize(
    ("urls", "expected"),
    [
        ((), ("", False)),
        (("https://www.tum.de/a", "https://www.cit.tum.de/b"), ("tum.de", True)),
        (("https://www.tum.de/a", "https://blogs.tum.de/b"), ("tum.de", False)),
        (("https://www.tum.de/a", "https://www.lmu.de/b"), ("", False)),
        (("https://foo.github.io/msc",), ("foo.github.io", False)),
        (("https://192.0.2.1/msc",), ("", False)),
    ],
)
def test_evidence_of(urls, expected) -> None:
    assert evidence_of(urls) == expected


def _write(url: str, institution_name: str):
    source = OfficialSource.objects.create(
        canonical_url=url, publisher="x", source_type=OfficialSource.Type.PROGRAM
    )
    snapshot = OfficialSourceSnapshot.objects.create(
        source=source, s3_key="k", s3_version_id="1", sha256="b" * 64, final_url=url,
        redirect_chain=[], retrieved_at=timezone.now(), admissions_cycle="2027",
        content_type="text/html", byte_size=10,
    )
    lead = ResearchLead.from_url(
        url, source_type="PROGRAM", funding_family="", discovered_by="test",
        identity=LeadIdentity(
            institution_name=institution_name, country_code="DE", city="Munich",
            program_name="MSc Informatics",
        ),
    )
    return write_catalog_entry(lead=lead, claims=CLAIMS, source=source, snapshot=snapshot)


def test_the_writer_records_the_evidence_domain_and_its_body() -> None:
    result = _write("https://www.tum.de/en/msc-informatics", "Technical University of Munich")
    assert result is not None
    assert (result.program.evidence_domain, result.program.evidence_institutional) == (
        "tum.de", True,
    )
    body = OrganisationDomain.objects.get(registrable_domain="tum.de").organisation
    assert body.kind == "INSTITUTION"
    assert body.country_code == ""  # the page's country is a claim, never evidence (§5.2)
    assert "CATALOG:programme" in body.found_via


def test_a_fake_page_naming_tum_lands_on_tums_row_but_keeps_its_own_evidence_domain() -> None:
    """Spec §1's hole, closed at the programme: the Institution is found by name
    and so is TUM's, but the programme's evidence is the fake's own domain."""
    real = _write("https://www.tum.de/en/msc-informatics", "Technical University of Munich")
    fake = _write("https://tum-admissions.com/msc", "Technical University of Munich")
    assert real is not None and fake is not None
    assert fake.institution == real.institution == Institution.objects.get()
    assert fake.program.evidence_domain == "tum-admissions.com"
    assert real.program.evidence_domain == "tum.de"


def test_a_second_page_on_a_user_subdomain_marks_the_programme_non_institutional() -> None:
    first = _write("https://www.tum.de/en/msc-informatics", "Technical University of Munich")
    second = _write("https://blogs.tum.de/en/msc-informatics", "Technical University of Munich")
    assert first is not None and second is not None
    assert second.program.id == first.program.id
    second.program.refresh_from_db()
    assert (second.program.evidence_domain, second.program.evidence_institutional) == (
        "tum.de", False,
    )


def test_a_hosting_platform_programme_records_no_body() -> None:
    result = _write("https://tum-msc.github.io/apply", "Technical University of Munich")
    assert result is not None
    assert result.program.evidence_domain == "tum-msc.github.io"
    assert not OrganisationDomain.objects.filter(registrable_domain="tum-msc.github.io").exists()
```

- [ ] **Step 2: Run them to verify they fail**

Run: `POSTGRES_DB=tehsil_provenance_gate uv run pytest tests/research/test_program_evidence.py -q --create-db`
Expected: FAIL with `ImportError: cannot import name 'evidence_of'`.

- [ ] **Step 3: Implement**

In `apps/research/provenance.py`, add `from collections.abc import Iterable`, then `from .hosts import is_institutional_url, registrable_domain`. After `verdict_of`, add:

```python
def evidence_of(urls: Iterable[str]) -> tuple[str, bool]:
    """(the single registrable domain of the evidence, whether it is all
    institutional) -- ("", False) when there is none or it disagrees (spec §3)."""
    listed = tuple(urls)
    domains = {registrable_domain(url) for url in listed}
    if len(domains) != 1 or "" in domains:
        return "", False
    domain = domains.pop()
    return domain, all(is_institutional_url(url, domain) for url in listed)
```

In `apps/research/catalog.py`:
- Add imports `from .hosts import is_hosting_platform`, `from .provenance import evidence_of` and `from .register import record_organisation`.
- After the `for claim_class, text in rows:` loop, before the `family = ...` block, insert:

```python
    # The programme's own evidence decides its body (institution provenance
    # gate spec §3) -- never the Institution row above, which is found by NAME
    # and so can be reached by a fake page naming a real university.
    domain, institutional = evidence_of(
        OfficialEvidenceClaim.objects.filter(program=program).values_list(
            "source__canonical_url", flat=True
        )
    )
    if (program.evidence_domain, program.evidence_institutional) != (domain, institutional):
        program.evidence_domain, program.evidence_institutional = domain, institutional
        program.save(update_fields=["evidence_domain", "evidence_institutional"])
    if domain and not is_hosting_platform(domain):
        # The body the verdict attaches to. No country: the page's country is
        # a model reading of the attacker's page (spec §5.2). The name is a
        # label, never a key.
        record_organisation(
            domain=domain, name=program_facts.institution_name, kind="INSTITUTION",
            country_code="", found_via="CATALOG:programme",
        )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `POSTGRES_DB=tehsil_provenance_gate uv run pytest tests/research/test_program_evidence.py tests/research/test_catalog_writer.py -q`
Expected: PASS.

- [ ] **Step 5: Run the four checks.** A catalogue write now also records the evidence body. If an existing test counts `Organisation` rows after one, the new body is expected: update the count and say why in a comment. Do not suppress the write.

- [ ] **Step 6: Commit**

```bash
git -C /home/orkhan/Desktop/provenance-gate add apps/research/provenance.py apps/research/catalog.py tests/research/provenance_helpers.py tests/research/test_program_evidence.py
git -C /home/orkhan/Desktop/provenance-gate commit -m "feat(research): programmes carry their own evidence domain and body"
```

---

### Task 4: `decide()`, the pure verdict function

**Files:**
- Modify: `apps/research/provenance.py`
- Test: `tests/research/test_provenance_decide.py`

**Interfaces:**
- Consumes: `hosts.is_hosting_platform`, `Verdict`, `Reason`.
- Produces (all in `apps.research.provenance`):
  - `Recognition(reason: str, bound_domain: str, source_slug: str = "", source_url: str = "", list_date: str = "", country_code: str = "", identifier: tuple[str, str] | None = None, vouch_url: str = "", admitted_via: str = "")` (frozen dataclass)
  - `MillHit(source: str, revision: str, country_code: str, overridden: bool)`
  - `ContentHit(reason: str, span: str, url: str)`
  - `RdapResult(status: str, registered: date | None = None, detail: str = "")`, where status is `"ok" | "skipped" | "failed"`
  - `Facts(domain: str, recognitions=(), unverified_list_row=False, mill=None, content_hits=(), content_checks="run", rdap=RdapResult("skipped"), first_bound_at=None, register_state="not_loaded", lookup_failed=False, was_vouched=False)`, where `register_state` is `"absent" | "unbound_rows" | "not_loaded"`
  - `Decision(verdict: str, reason_code: str, bound_domain: str, evidence: dict[str, object])`
  - `decide(facts: Facts) -> Decision`

- [ ] **Step 1: Write the failing tests**

Create `tests/research/test_provenance_decide.py`:

```python
"""decide(): evidence in, one verdict out. Pure -- no database, no network,
and no model call anywhere on the admit path (spec §2)."""

from datetime import UTC, date, datetime

import pytest

from apps.research.provenance import (
    ContentHit,
    Facts,
    MillHit,
    RdapResult,
    Recognition,
    decide,
)

REGISTER = Recognition(
    reason="register", bound_domain="tum.de", source_slug="de_register",
    source_url="https://register.example.org/", list_date="2026-09-26", country_code="DE",
)
CURATED = Recognition(reason="curated_list", bound_domain="tum.de", source_slug="az_heis")
VOUCHED = Recognition(
    reason="vouched_by_link", bound_domain="ufaz.az", vouch_url="https://asoiu.edu.az/",
    admitted_via="asoiu.edu.az",
)
VENDOR = ContentHit(reason="degree_for_payment", span="Buy your MBA today.", url="https://x/")


def test_a_register_row_recognises_the_bound_domain_and_records_its_source() -> None:
    decision = decide(Facts(domain="tum.de", recognitions=(REGISTER,)))
    assert (decision.verdict, decision.reason_code, decision.bound_domain) == (
        "RECOGNISED", "register", "tum.de",
    )
    assert decision.evidence["source_slug"] == "de_register"
    assert decision.evidence["list_date"] == "2026-09-26"


def test_the_strongest_route_wins_whatever_the_order() -> None:
    decision = decide(Facts(domain="tum.de", recognitions=(CURATED, REGISTER)))
    assert decision.reason_code == "register"


def test_vouching_records_the_link_it_rests_on() -> None:
    decision = decide(Facts(domain="ufaz.az", recognitions=(VOUCHED,)))
    assert decision.reason_code == "vouched_by_link"
    assert decision.evidence["vouch_url"] == "https://asoiu.edu.az/"
    assert decision.evidence["admitted_via"] == "asoiu.edu.az"


def test_a_hosting_platform_can_never_be_recognised_by_its_domain() -> None:
    on_platform = Recognition(reason="curated_list", bound_domain="tum.blogspot.com")
    decision = decide(Facts(domain="tum.blogspot.com", recognitions=(on_platform,)))
    assert (decision.verdict, decision.reason_code) == ("UNCONFIRMED", "no_domain_binding")


def test_a_mill_blocks_unless_its_own_countrys_register_overrides_it() -> None:
    mill = MillHit(source="wikipedia", revision="1376085262", country_code="GB", overridden=False)
    blocked = decide(Facts(domain="warnborough.ac.uk", recognitions=(REGISTER,), mill=mill))
    assert (blocked.verdict, blocked.reason_code) == ("BLOCKED", "mill_list")
    assert blocked.evidence["mill"] == {
        "source": "wikipedia", "revision": "1376085262", "country_code": "GB",
    }
    overridden = MillHit(source="wikipedia", revision="1", country_code="DE", overridden=True)
    assert decide(Facts(domain="tum.de", recognitions=(REGISTER,), mill=overridden)).verdict == (
        "RECOGNISED"
    )


def test_a_content_veto_on_a_recognised_body_is_a_conflict_never_a_block() -> None:
    decision = decide(Facts(domain="esmt.berlin", recognitions=(REGISTER,), content_hits=(VENDOR,)))
    assert (decision.verdict, decision.reason_code) == ("UNCONFIRMED", "veto_conflict")
    assert decision.evidence["content_hits"] == [
        {"reason": "degree_for_payment", "span": "Buy your MBA today.", "url": "https://x/"}
    ]


def test_a_content_veto_on_an_unrecognised_body_blocks() -> None:
    decision = decide(Facts(domain="diploma-shop.com", content_hits=(VENDOR,)))
    assert (decision.verdict, decision.reason_code) == ("BLOCKED", "degree_for_payment")


def test_a_domain_registered_after_we_first_bound_it_is_unconfirmed() -> None:
    facts = Facts(
        domain="esmt.berlin", recognitions=(REGISTER,),
        rdap=RdapResult("ok", registered=date(2016, 6, 6)),
        first_bound_at=datetime(2015, 1, 1, tzinfo=UTC),
    )
    decision = decide(facts)
    assert (decision.verdict, decision.reason_code) == (
        "UNCONFIRMED", "domain_registered_after_listing",
    )
    assert decision.evidence["rdap"] == {"status": "ok", "date": "2016-06-06", "detail": ""}


@pytest.mark.parametrize("rdap", [RdapResult("skipped", detail=".de"), RdapResult("failed")])
def test_an_rdap_gap_never_changes_a_recognised_verdict(rdap) -> None:
    facts = Facts(
        domain="tum.de", recognitions=(REGISTER,), rdap=rdap,
        first_bound_at=datetime(2015, 1, 1, tzinfo=UTC),
    )
    assert decide(facts).verdict == "RECOGNISED"


@pytest.mark.parametrize(
    ("facts", "reason"),
    [
        (Facts(domain="asoiu.edu.az", unverified_list_row=True), "unmapped_list_row"),
        (Facts(domain="ufaz.az", was_vouched=True), "vouch_link_missing"),
        (Facts(domain="uni.example.com", lookup_failed=True), "lookup_failed"),
        (Facts(domain="nyenrode.nl", register_state="unbound_rows"), "no_domain_binding"),
        (Facts(domain="dubai-branch.ae", register_state="absent"), "absent_from_register"),
        (Facts(domain="uni.jp", register_state="not_loaded"), "register_not_loaded"),
        (Facts(domain="uni.wixsite.com", register_state="absent"), "no_domain_binding"),
    ],
)
def test_every_unconfirmed_reason(facts, reason) -> None:
    decision = decide(facts)
    assert (decision.verdict, decision.reason_code) == ("UNCONFIRMED", reason)


def test_absence_is_never_blocked() -> None:
    for state in ("absent", "unbound_rows", "not_loaded"):
        assert decide(Facts(domain="little-known.edu", register_state=state)).verdict != "BLOCKED"


def test_skipped_content_checks_are_recorded() -> None:
    decision = decide(Facts(domain="tum.de", recognitions=(REGISTER,), content_checks="skipped"))
    assert decision.evidence["content_checks"] == "skipped"
```

- [ ] **Step 2: Run them to verify they fail**

Run: `POSTGRES_DB=tehsil_provenance_gate uv run pytest tests/research/test_provenance_decide.py -q --create-db`
Expected: FAIL with `ImportError: cannot import name 'ContentHit'`.

- [ ] **Step 3: Implement**

In `apps/research/provenance.py`:
- Add `from dataclasses import dataclass, field` and `from datetime import date, datetime` (replacing the plain `datetime` import).
- Extend the hosts import to `from .hosts import is_hosting_platform, is_institutional_url, registrable_domain`.
- Append:

```python
@dataclass(frozen=True)
class Recognition:
    """One route that names the body and binds it to `bound_domain` (spec §5.1-§5.3, §5.7)."""

    reason: str
    bound_domain: str
    source_slug: str = ""
    source_url: str = ""
    list_date: str = ""
    #: The country of a register row -- the only country a mill-list entry
    #: accepts as an override (spec §5.4 rule 1).
    country_code: str = ""
    identifier: tuple[str, str] | None = None
    vouch_url: str = ""
    admitted_via: str = ""


@dataclass(frozen=True)
class MillHit:
    source: str
    revision: str
    country_code: str
    overridden: bool


@dataclass(frozen=True)
class ContentHit:
    reason: str
    span: str
    url: str


@dataclass(frozen=True)
class RdapResult:
    status: str
    registered: date | None = None
    detail: str = ""


@dataclass(frozen=True)
class Facts:
    domain: str
    recognitions: tuple[Recognition, ...] = ()
    unverified_list_row: bool = False
    mill: MillHit | None = None
    content_hits: tuple[ContentHit, ...] = ()
    content_checks: str = "run"
    rdap: RdapResult = field(default_factory=lambda: RdapResult("skipped"))
    first_bound_at: datetime | None = None
    register_state: str = "not_loaded"
    lookup_failed: bool = False
    was_vouched: bool = False


@dataclass(frozen=True)
class Decision:
    verdict: str
    reason_code: str
    bound_domain: str
    evidence: dict[str, object]


#: Strongest first. A register is the authority itself; a vouch is one hop
#: from one.
_PRIORITY: tuple[str, ...] = (
    Reason.REGISTER, Reason.CURATED_LIST, Reason.FUNDER_LIST,
    Reason.GOVERNMENT_ZONE, Reason.VOUCHED_BY_LINK,
)


def decide(facts: Facts) -> Decision:
    """Evidence to verdict (spec §4, §5). Order, and it is the whole function:

    1. a mill-list domain, not overridden by its own country's register -> BLOCKED;
    2. a usable recognition -> RECOGNISED, unless a content veto hit
       (veto_conflict) or the domain was registered after we first bound it;
    3. no recognition and a content veto hit -> BLOCKED;
    4. otherwise UNCONFIRMED, with the most specific reason. Absence is never BLOCKED.
    """
    evidence: dict[str, object] = {
        "content_checks": facts.content_checks,
        "rdap": {
            "status": facts.rdap.status,
            "date": facts.rdap.registered.isoformat() if facts.rdap.registered else "",
            "detail": facts.rdap.detail,
        },
    }
    if facts.content_hits:
        evidence["content_hits"] = [
            {"reason": hit.reason, "span": hit.span[:300], "url": hit.url}
            for hit in facts.content_hits
        ]
    if facts.mill is not None and not facts.mill.overridden:
        evidence["mill"] = {
            "source": facts.mill.source,
            "revision": facts.mill.revision,
            "country_code": facts.mill.country_code,
        }
        return Decision(Verdict.BLOCKED, Reason.MILL_LIST, facts.domain, evidence)
    usable = sorted(
        (r for r in facts.recognitions if not is_hosting_platform(r.bound_domain)),
        key=lambda r: _PRIORITY.index(r.reason),
    )
    if usable:
        chosen = usable[0]
        evidence.update(
            {
                "source_slug": chosen.source_slug,
                "source_url": chosen.source_url,
                "list_date": chosen.list_date,
                "identifier": (
                    {"scheme": chosen.identifier[0], "value": chosen.identifier[1]}
                    if chosen.identifier
                    else None
                ),
                "vouch_url": chosen.vouch_url,
                "admitted_via": chosen.admitted_via,
            }
        )
        if facts.content_hits:
            return Decision(Verdict.UNCONFIRMED, Reason.VETO_CONFLICT, chosen.bound_domain, evidence)
        if _taken_over(facts):
            return Decision(
                Verdict.UNCONFIRMED, Reason.DOMAIN_REGISTERED_AFTER_LISTING,
                chosen.bound_domain, evidence,
            )
        return Decision(Verdict.RECOGNISED, chosen.reason, chosen.bound_domain, evidence)
    if facts.content_hits:
        return Decision(Verdict.BLOCKED, facts.content_hits[0].reason, facts.domain, evidence)
    return Decision(Verdict.UNCONFIRMED, _unconfirmed_reason(facts), facts.domain, evidence)


def _taken_over(facts: Facts) -> bool:
    """Registered after OUR first binding: a re-registered expired domain looks
    exactly like this, and so does a rebrand -- hence UNCONFIRMED, never BLOCKED."""
    return (
        facts.rdap.status == "ok"
        and facts.rdap.registered is not None
        and facts.first_bound_at is not None
        and facts.rdap.registered > facts.first_bound_at.date()
    )


def _unconfirmed_reason(facts: Facts) -> str:
    if facts.unverified_list_row:
        return Reason.UNMAPPED_LIST_ROW
    if facts.was_vouched:
        return Reason.VOUCH_LINK_MISSING
    if facts.lookup_failed:
        return Reason.LOOKUP_FAILED
    if is_hosting_platform(facts.domain) or facts.register_state == "unbound_rows":
        return Reason.NO_DOMAIN_BINDING
    if facts.register_state == "absent":
        return Reason.ABSENT_FROM_REGISTER
    return Reason.REGISTER_NOT_LOADED
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `POSTGRES_DB=tehsil_provenance_gate uv run pytest tests/research/test_provenance_decide.py -q`
Expected: PASS.

- [ ] **Step 5: Run the four checks.**

- [ ] **Step 6: Commit**

```bash
git -C /home/orkhan/Desktop/provenance-gate add apps/research/provenance.py tests/research/test_provenance_decide.py
git -C /home/orkhan/Desktop/provenance-gate commit -m "feat(research): decide() turns provenance evidence into one verdict"
```

---

### Task 5: Reviewed lists and funder lists as evidence, with origin verification

**Files:**
- Create:
  - `apps/research/recognition.py`
  - `apps/research/management/commands/verify_list_origins.py`
  - `docs/research/provenance-sources.csv`
  - `docs/research/closed-lists/national_scholarship_agencies.csv`
- Modify: `apps/research/closed_lists.py:282-295` (`record_list` writes `website_domain`), `docs/research/closed-lists.csv`
- Test: `tests/research/test_recognition_lists.py`

**Interfaces:**
- Consumes:
  - `closed_lists.read_registry`, `closed_lists.record_list`, `closed_lists.ListRow`, `closed_lists.DATA_DIR`, `closed_lists.REGISTRY`
  - `fetch.fetch_page`, `harvest.page_text`, `provenance.Recognition`, `provenance.Reason`
- Produces (all in `apps.research.recognition`):
  - `SOURCES: Path`
  - `ProvenanceSource(slug, role, enic_naric_page="", named_by_hand_because="", data_url="", format="", encoding="utf-8", records_path="", name_field="", website_field="", id_field="", id_scheme="", list_anchor="", max_bytes=MAX_RESPONSE_BYTES)`
  - `SourceFileError`
  - `read_sources(path: Path = SOURCES, registry: Path = REGISTRY) -> tuple[ProvenanceSource, ...]`
  - `usable(page: FetchedPage) -> bool`
  - `list_recognitions(organisation: Organisation, sources: tuple[ProvenanceSource, ...] | None = None) -> tuple[tuple[Recognition, ...], bool]`
  - `GOVERNMENT_ZONES: tuple[tuple[str, str], ...]`
  - `government_zone(domain: str) -> Recognition | None`
  - `name_variants(name: str) -> tuple[str, ...]`
  - `verify_origin(entry: RegisterEntry, *, now: datetime, fetch=None) -> str`
  - `verify_list_origins(slugs: Iterable[str], *, now: datetime, fetch=None) -> list[tuple[str, str, str]]`
  - The `manage.py verify_list_origins [--list SLUG]` command

Spec corrections for this task:

- **Evidence lists are named, not chosen by rung.** §5.7 names `az_outbound_gov`, `az_bilateral` and `tr_bilateral` as evidence, but they are rung 3 in `closed-lists.csv`, so "REGISTERED counts only at rung ≤ 2" cannot be the rule. Evidence lists are named in `provenance-sources.csv` instead.
- **Joint rule 2 (§3) goes through EACEA partners.** No `Program`↔`RegisterEntry` link exists (`eacea.py` docstring). EACEA partners are the `funder_list` route, so a joint programme on a partner's domain passes by joint rule 1.
- **Only six government zones ship.** Only the zones whose registry citation was fetched on 2026-09-26 ship: `gov` (get.gov requirements), `gov.tr` (TRABİS, already cited in `domains.py`), `go.jp` (JPRS), `go.kr` (KISA), `europa.eu` and `auswaertiges-amt.de`. The implementer re-reads each cited page and drops any entry whose page does not state that the zone is restricted to government bodies. Each remaining zone the spec names (`gov.uk`, `gov.az`, `gouv.fr`, `gov.cn`, `gob.es`/`gob.mx`, `bund.de`, `bmbf.de`, `gc.ca`) is a later one-line change carrying its citation.

- [ ] **Step 1: Add the data**

Create `docs/research/provenance-sources.csv`:

```csv
slug,role,enic_naric_page,named_by_hand_because,data_url,format,encoding,records_path,name_field,website_field,id_field,id_scheme,list_anchor,max_bytes
az_heis,curated_list,,,,,,,,,,,,
tr_heis,curated_list,,,,,,,,,,,,
igo_regional_global,curated_list,,,,,,,,,,,,
az_outbound_gov,curated_list,,,,,,,,,,,,
az_bilateral,curated_list,,,,,,,,,,,,
tr_bilateral,curated_list,,,,,,,,,,,,
national_scholarship_agencies,curated_list,,,,,,,,,,,,
eacea_emjm,funder_list,,,,,,,,,,,,
```

Append to `docs/research/closed-lists.csv`:

```csv
national_scholarship_agencies,"National scholarship agencies with no open register (DAAD, Campus France, SI, Chevening, Stipendium Hungaricum, CSC)",,NATIONAL_GOVERNMENT,1,https://github.com/0rkhann/tehsil_agent/blob/master/docs/research/closed-lists/national_scholarship_agencies.csv,tehsil_agent (compiled from each body's own page),yes,yes,OWN_COMPILATION,,yes,ENUMERATE_ONLY,,2026-09-26
```

Create `docs/research/closed-lists/national_scholarship_agencies.csv`:

```csv
external_key,name,kind,website,page_url,country_code,home_cells,host_cells,rejected_reason,source_url,verified_on,notes
daad,Deutscher Akademischer Austauschdienst (DAAD),NATIONAL_GOVERNMENT,https://www.daad.de,,DE,ANY,DE,,https://www.daad.de/de/,2026-09-26,"homepage title 2026-09-26: 'Deutscher Akademischer Austauschdienst - DAAD'; a registered association with no open register (spec §5.7); verify_list_origins confirms the origin"
campus-france,Campus France,NATIONAL_GOVERNMENT,https://www.campusfrance.org,,FR,ANY,FR,,https://www.campusfrance.org/fr,2026-09-26,"homepage title 2026-09-26: 'Étudiants | Campus France : étudier en France'"
si,Swedish Institute (Svenska institutet),NATIONAL_GOVERNMENT,https://si.se,,SE,ANY,SE,,https://si.se/,2026-09-26,"homepage title 2026-09-26 names Svenska institutet"
chevening,Chevening Scholarships,NATIONAL_GOVERNMENT,https://www.chevening.org,,GB,ANY,GB,,https://www.chevening.org/,2026-09-26,"origin did not answer a plain client on 2026-09-26; stays unmapped_list_row until verify_list_origins reads it"
stipendium-hungaricum,Stipendium Hungaricum,NATIONAL_GOVERNMENT,https://stipendiumhungaricum.hu,,HU,ANY,HU,,https://stipendiumhungaricum.hu/,2026-09-26,"homepage title 2026-09-26: 'Stipendium Hungaricum - Stipendium Hungaricum'"
csc,China Scholarship Council (CampusChina),NATIONAL_GOVERNMENT,https://www.campuschina.org,,CN,ANY,CN,,https://www.campuschina.org/,2026-09-26,"HTTP 412 to a plain client on 2026-09-26; verify_list_origins reads it through the vendor ladder"
```

- [ ] **Step 2: Write the failing tests**

Create `tests/research/test_recognition_lists.py`:

```python
"""Reviewed lists and funder lists as admission evidence (spec §5.1 points 2-3,
§5.7, §13.8). A reviewed row counts only once its origin named the institution."""

from dataclasses import replace
from datetime import date
from io import StringIO
from pathlib import Path

import pytest
from django.core.management import call_command
from django.utils import timezone

from apps.research.closed_lists import ListRow, read_list_file, read_registry, record_list
from apps.research.models import (
    ClosedList,
    Organisation,
    OrganisationDomain,
    RegisterEntry,
    RegisterEntryPartner,
)
from apps.research.recognition import (
    GOVERNMENT_ZONES,
    ProvenanceSource,
    SourceFileError,
    government_zone,
    list_recognitions,
    name_variants,
    read_sources,
    verify_list_origins,
)
from tests.research.provenance_helpers import FakeFetch, make_body, make_list, page

pytestmark = pytest.mark.django_db

CURATED = (
    ProvenanceSource(slug="az_heis", role="curated_list"),
    ProvenanceSource(slug="national_scholarship_agencies", role="curated_list"),
    ProvenanceSource(slug="eacea_emjm", role="funder_list"),
)
ASOIU = ListRow(
    external_key="az-hei-asoiu", name="Azerbaijan State Oil and Industry University (ADNSU)",
    kind="INSTITUTION", website="https://asoiu.edu.az", page_url="", country_code="AZ",
    home_cells=("ANY",), host_cells=("AZ",), rejected_reason="",
    source_url="https://edu.gov.az/az/higher-education/ali-tehsil-muessiseleri",
    verified_on=date(2026, 9, 26),
)


def _asoiu() -> Organisation:
    record_list(make_list("az_heis", country_code="AZ"), (ASOIU,), now=timezone.now())
    return OrganisationDomain.objects.get(registrable_domain="asoiu.edu.az").organisation


def test_the_shipped_sources_parse_and_every_slug_has_a_registry_row() -> None:
    sources = read_sources()
    slugs = {str(spec["slug"]) for spec in read_registry()}
    assert {source.slug for source in sources} <= slugs
    assert {"az_heis", "az_outbound_gov", "az_bilateral", "tr_bilateral",
            "igo_regional_global", "national_scholarship_agencies"} <= {
        source.slug for source in sources if source.role == "curated_list"
    }
    assert {source.slug for source in sources if source.role == "funder_list"} == {"eacea_emjm"}


def test_the_agencies_list_names_the_six_funders_the_spec_names() -> None:
    spec = ClosedList(**next(s for s in read_registry() if s["slug"] == "national_scholarship_agencies"))
    websites = {row.website for row in read_list_file(spec)}
    assert websites == {
        "https://www.daad.de/", "https://www.campusfrance.org/", "https://si.se/",
        "https://www.chevening.org/", "https://stipendiumhungaricum.hu/",
        "https://www.campuschina.org/",
    }


@pytest.mark.parametrize(
    ("row", "error"),
    [
        ("nowhere,curated_list,,,,,,,,,,,,", "has no row in closed-lists.csv"),
        ("az_heis,a_rumour,,,,,,,,,,,,", "role"),
        ("az_heis,register,,,https://x.example.org/f.tsv,tsv,utf-8,,Name,Web,,,,",
         "ENIC-NARIC page or says why"),
        ("az_heis,register,,by hand,http://x.example.org/f.tsv,tsv,utf-8,,Name,Web,,,,", "https"),
        ("az_heis,register,,by hand,https://x.example.org/f,html_list,utf-8,,,,,,,", "list_anchor"),
    ],
)
def test_a_bad_sources_row_is_named_by_line(tmp_path: Path, row: str, error: str) -> None:
    path = tmp_path / "provenance-sources.csv"
    path.write_text(
        "slug,role,enic_naric_page,named_by_hand_because,data_url,format,encoding,"
        "records_path,name_field,website_field,id_field,id_scheme,list_anchor,max_bytes\n"
        + row + "\n",
        encoding="utf-8",
    )
    with pytest.raises(SourceFileError, match=error):
        read_sources(path)


def test_record_list_stores_the_domain_it_bound_by() -> None:
    _asoiu()
    assert RegisterEntry.objects.get(external_key="az-hei-asoiu").website_domain == "asoiu.edu.az"


def test_a_reviewed_row_counts_only_after_its_origin_names_the_institution() -> None:
    """Spec §13.8: az_heis's websites came from search, origin not fetched."""
    body = _asoiu()
    assert list_recognitions(body, CURATED) == ((), True)

    fetch = FakeFetch({"https://asoiu.edu.az/": page(
        "https://asoiu.edu.az/",
        "<html><title>ADNSU | Azərbaycan Dövlət Neft və Sənaye Universiteti</title></html>",
    )})
    assert verify_list_origins(["az_heis"], now=timezone.now(), fetch=fetch) == [
        ("az_heis", "az-hei-asoiu", "verified")
    ]
    found, unverified = list_recognitions(body, CURATED)
    assert [(r.reason, r.bound_domain, r.source_slug, r.list_date) for r in found] == [
        ("curated_list", "asoiu.edu.az", "az_heis", "2026-09-26")
    ]
    assert unverified is False


@pytest.mark.parametrize(
    ("fetched", "outcome"),
    [
        (page("https://asoiu.edu.az/", "<title>Domain for sale</title>"),
         "the page does not name the institution"),
        (page("https://asoiu.edu.az/", "<title>ADNSU</title>",
              final_url="https://parked-domains.com/lander"),
         "redirected off the listed domain to https://parked-domains.com/lander"),
    ],
)
def test_an_origin_that_does_not_confirm_the_row_leaves_it_unverified(fetched, outcome) -> None:
    body = _asoiu()
    fetch = FakeFetch({"https://asoiu.edu.az/": fetched})
    assert verify_list_origins(["az_heis"], now=timezone.now(), fetch=fetch) == [
        ("az_heis", "az-hei-asoiu", outcome)
    ]
    assert list_recognitions(body, CURATED) == ((), True)


def test_an_unreachable_origin_is_reported_not_verified() -> None:
    _asoiu()
    [(_, _, outcome)] = verify_list_origins(["az_heis"], now=timezone.now(), fetch=FakeFetch({}))
    assert outcome.startswith("not fetched (DEAD")


def test_a_changed_website_voids_the_verification() -> None:
    _asoiu()
    fetch = FakeFetch({"https://asoiu.edu.az/": page("https://asoiu.edu.az/", "<title>ADNSU</title>")})
    verify_list_origins(["az_heis"], now=timezone.now(), fetch=fetch)
    moved = replace(ASOIU, website="https://asoiu-new.az")
    record_list(ClosedList.objects.get(slug="az_heis"), (moved,), now=timezone.now())
    new_body = OrganisationDomain.objects.get(registrable_domain="asoiu-new.az").organisation
    assert list_recognitions(new_body, CURATED) == ((), True)


def test_daad_is_recognised_through_the_reviewed_agencies_list() -> None:
    row = ListRow(
        external_key="daad", name="Deutscher Akademischer Austauschdienst (DAAD)",
        kind="NATIONAL_GOVERNMENT", website="https://www.daad.de", page_url="",
        country_code="DE", home_cells=("ANY",), host_cells=("DE",), rejected_reason="",
        source_url="https://www.daad.de/de/", verified_on=date(2026, 9, 26),
    )
    record_list(
        make_list("national_scholarship_agencies", holder_kinds=("NATIONAL_GOVERNMENT",)),
        (row,), now=timezone.now(),
    )
    fetch = FakeFetch({"https://daad.de/": page(
        "https://daad.de/", "<title>Deutscher Akademischer Austauschdienst - DAAD</title>",
        final_url="https://www.daad.de/de/",
    )})
    assert verify_list_origins(["national_scholarship_agencies"], now=timezone.now(), fetch=fetch)[0][2] == "verified"
    body = OrganisationDomain.objects.get(registrable_domain="daad.de").organisation
    found, _ = list_recognitions(body, CURATED)
    assert [(r.reason, r.bound_domain) for r in found] == [("curated_list", "daad.de")]


def test_a_lookalike_funder_binds_to_nothing() -> None:
    body = make_body("daad-scholarships.org", kind="PRIVATE_FOUNDATION")
    assert list_recognitions(body, CURATED) == ((), False)
    assert government_zone("daad-scholarships.org") is None


def test_an_eacea_partner_is_a_funder_list_body_keyed_by_its_pic() -> None:
    body = make_body("unibo.it")
    entry = RegisterEntry.objects.create(
        register="eacea_emjm", external_key="101", name="EMJM X", resolution="RESOLVED",
        last_seen=timezone.now(),
    )
    RegisterEntryPartner.objects.create(
        entry=entry, organisation=body, role="PARTNER", listed_name="Università di Bologna",
        listed_identifier="999880560", listed_domain="unibo.it", disposition="BOUND_BOTH",
    )
    other = make_body("conflict.it")
    RegisterEntryPartner.objects.create(
        entry=entry, organisation=None, role="PARTNER", listed_name="Conflict",
        listed_identifier="1", listed_domain="conflict.it", disposition="CONFLICT",
    )
    found, _ = list_recognitions(body, CURATED)
    assert [(r.reason, r.bound_domain, r.identifier) for r in found] == [
        ("funder_list", "unibo.it", ("EACEA_PIC", "999880560"))
    ]
    assert list_recognitions(other, CURATED) == ((), False)


@pytest.mark.parametrize(
    ("domain", "zone"),
    [
        ("studyinkorea.go.kr", "go.kr"),
        ("mext.go.jp", "go.jp"),
        ("ed.gov", "gov"),
        ("turkiyeburslari.gov.tr", "gov.tr"),
        ("europa.eu", "europa.eu"),
        ("auswaertiges-amt.de", "auswaertiges-amt.de"),
    ],
)
def test_a_government_zone_recognises_a_funder(domain: str, zone: str) -> None:
    recognition = government_zone(domain)
    assert recognition is not None
    assert (recognition.reason, recognition.bound_domain, recognition.source_slug) == (
        "government_zone", domain, f"zone:{zone}",
    )


@pytest.mark.parametrize("domain", ["gov.example.com", "govscholarships.com", "gov-az.org"])
def test_a_gov_pattern_alone_is_never_proof(domain: str) -> None:
    assert government_zone(domain) is None


def test_every_zone_cites_its_registry_policy() -> None:
    assert GOVERNMENT_ZONES
    assert all(citation.startswith("https://") for _zone, citation in GOVERNMENT_ZONES)


def test_name_variants() -> None:
    assert name_variants("Azerbaijan State Oil and Industry University (ADNSU)") == (
        "azerbaijan state oil and industry university", "adnsu",
    )


def test_the_command_reports_each_row(monkeypatch) -> None:
    _asoiu()
    monkeypatch.setattr(
        "apps.research.recognition.fetch_page",
        FakeFetch({"https://asoiu.edu.az/": page("https://asoiu.edu.az/", "<b>ADNSU</b>")}),
    )
    out = StringIO()
    call_command("verify_list_origins", "--list", "az_heis", stdout=out)
    assert "az_heis az-hei-asoiu: verified" in out.getvalue()
```

- [ ] **Step 3: Run them to verify they fail**

Run: `POSTGRES_DB=tehsil_provenance_gate uv run pytest tests/research/test_recognition_lists.py -q --create-db`
Expected: FAIL with `ModuleNotFoundError: No module named 'apps.research.recognition'`.

- [ ] **Step 4: Implement**

In `apps/research/closed_lists.py`'s `record_list`, add `"website_domain": domain,` to the `update_or_create` `defaults` dict, after `"last_seen": now,`.

Create `apps/research/recognition.py`:

```python
"""Who may vouch for a body, read as data (institution provenance gate spec
§5.1, §5.2, §5.7, §13.8).

Every route here binds a body to a domain through a list row a person reviewed,
a register's own website field, or an identifier -- never a name. Which lists
count, and in which role, is `docs/research/provenance-sources.csv`: one
reviewed row per source, keyed by its `closed-lists.csv` slug, so adding a
country or a list is a one-row diff and never a per-school step.
"""

from __future__ import annotations

import csv
import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .closed_lists import DATA_DIR, REGISTRY, read_registry
from .egress import MAX_RESPONSE_BYTES
from .fetch import fetch_page
from .fetch.types import FetchedPage, Outcome
from .harvest import page_text
from .hosts import registrable_domain
from .models import ClosedList, Organisation, RegisterEntry, RegisterEntryPartner
from .provenance import Reason, Recognition

logger = logging.getLogger(__name__)

SOURCES = DATA_DIR / "provenance-sources.csv"
_SOURCE_COLUMNS = (
    "slug", "role", "enic_naric_page", "named_by_hand_because", "data_url", "format",
    "encoding", "records_path", "name_field", "website_field", "id_field", "id_scheme",
    "list_anchor", "max_bytes",
)
ROLES = (Reason.REGISTER, Reason.CURATED_LIST, Reason.FUNDER_LIST)
FORMATS = ("tsv", "json_list", "html_list")
_UNBOUND = ("CONFLICT", "NO_KEY")

Fetch = Callable[..., FetchedPage]


class SourceFileError(ValueError):
    """A provenance-sources row that does not say what the loader needs."""


@dataclass(frozen=True)
class ProvenanceSource:
    slug: str
    role: str
    enic_naric_page: str = ""
    named_by_hand_because: str = ""
    data_url: str = ""
    format: str = ""
    encoding: str = "utf-8"
    records_path: str = ""
    name_field: str = ""
    website_field: str = ""
    id_field: str = ""
    id_scheme: str = ""
    list_anchor: str = ""
    max_bytes: int = MAX_RESPONSE_BYTES


def read_sources(path: Path = SOURCES, registry: Path = REGISTRY) -> tuple[ProvenanceSource, ...]:
    known = {str(spec["slug"]) for spec in read_registry(registry)}
    sources: list[ProvenanceSource] = []
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != _SOURCE_COLUMNS:
            raise SourceFileError(f"{path.name}: columns {reader.fieldnames} are not {_SOURCE_COLUMNS}")
        for line, raw in enumerate(reader, start=2):
            where = f"{path.name}:{line}"
            row = {key: (value or "").strip() for key, value in raw.items()}
            if row["slug"] not in known:
                raise SourceFileError(f"{where}: {row['slug']!r} has no row in closed-lists.csv")
            if row["role"] not in ROLES:
                raise SourceFileError(f"{where}: role {row['role']!r} is not one of {ROLES}")
            if row["role"] == Reason.REGISTER:
                if not (row["enic_naric_page"] or row["named_by_hand_because"]):
                    raise SourceFileError(
                        f"{where}: a register names its ENIC-NARIC page or says why it is "
                        "named by hand (spec §5.1: ENIC-NARIC is the root of trust)"
                    )
                if not row["data_url"].startswith("https://"):
                    raise SourceFileError(f"{where}: data_url must be https")
                if row["format"] not in FORMATS:
                    raise SourceFileError(f"{where}: format {row['format']!r} is not {FORMATS}")
                if row["format"] == "html_list" and not row["list_anchor"]:
                    raise SourceFileError(f"{where}: an html_list needs a list_anchor")
                if row["format"] != "html_list" and not (row["name_field"] and row["website_field"]):
                    raise SourceFileError(f"{where}: name_field and website_field are required")
            sources.append(
                ProvenanceSource(
                    slug=row["slug"], role=row["role"], enic_naric_page=row["enic_naric_page"],
                    named_by_hand_because=row["named_by_hand_because"], data_url=row["data_url"],
                    format=row["format"], encoding=row["encoding"] or "utf-8",
                    records_path=row["records_path"], name_field=row["name_field"],
                    website_field=row["website_field"], id_field=row["id_field"],
                    id_scheme=row["id_scheme"], list_anchor=row["list_anchor"],
                    max_bytes=int(row["max_bytes"]) if row["max_bytes"] else MAX_RESPONSE_BYTES,
                )
            )
    return tuple(sources)


def usable(page: FetchedPage) -> bool:
    """A page with bytes a caller may read. UNCHANGED carries its body too
    (fetch/__init__.py, `_CARRIES_BYTES`)."""
    return bool(page.body) and (page.ok or page.outcome == Outcome.UNCHANGED)


def list_recognitions(
    organisation: Organisation, sources: tuple[ProvenanceSource, ...] | None = None
) -> tuple[tuple[Recognition, ...], bool]:
    """(recognitions from list rows bound to this body, whether a reviewed row
    names it but its origin is not verified yet -> unmapped_list_row)."""
    sources = sources if sources is not None else read_sources()
    by_slug = {source.slug: source for source in sources}
    lists = ClosedList.objects.in_bulk(list(by_slug))
    found: list[Recognition] = []
    unverified = False
    entries = RegisterEntry.objects.filter(
        organisation=organisation, register__in=list(by_slug),
        resolution=RegisterEntry.Resolution.RESOLVED,
    ).exclude(website_domain="")
    for entry in entries:
        source = by_slug[entry.register]
        if source.role == Reason.CURATED_LIST and entry.origin_verified_domain != entry.website_domain:
            unverified = True
            continue
        spec = lists.get(entry.register)
        found.append(
            Recognition(
                reason=source.role, bound_domain=entry.website_domain, source_slug=entry.register,
                source_url=spec.source_url if spec else "",
                list_date=spec.verified_on.isoformat() if spec else "",
                country_code=spec.country_code if spec else "",
                identifier=(source.id_scheme, entry.external_key) if source.id_scheme else None,
            )
        )
    funder_slugs = [source.slug for source in sources if source.role == Reason.FUNDER_LIST]
    partners = (
        RegisterEntryPartner.objects.filter(organisation=organisation, entry__register__in=funder_slugs)
        .exclude(listed_domain="")
        .exclude(disposition__in=_UNBOUND)
        .select_related("entry")
    )
    for partner in partners:
        spec = lists.get(partner.entry.register)
        found.append(
            Recognition(
                reason=Reason.FUNDER_LIST, bound_domain=partner.listed_domain,
                source_slug=partner.entry.register,
                source_url=spec.source_url if spec else "",
                list_date=spec.verified_on.isoformat() if spec else "",
                identifier=("EACEA_PIC", partner.listed_identifier),
            )
        )
    return tuple(found), unverified


#: Government-only zones, each with the registry policy that restricts it
#: (spec §5.7), fetched 2026-09-26. A `gov.*` pattern alone is never proof; a
#: zone is added only with its citation. Pinned by test_recognition_lists.py.
GOVERNMENT_ZONES: tuple[tuple[str, str], ...] = (
    ("gov", "https://get.gov/domains/requirements/"),
    ("gov.tr", "https://www.trabis.gov.tr/"),
    ("go.jp", "https://jprs.co.jp/en/jpdomain.html"),
    ("go.kr", "https://xn--3e0bx5euxnjje69i70af08bea817g.xn--3e0b707e/jsp/eng/domain/domainInfo.jsp"),
    ("europa.eu", "https://european-union.europa.eu/index_en"),
    ("auswaertiges-amt.de", "https://www.auswaertiges-amt.de/de/impressum"),
)


def government_zone(domain: str) -> Recognition | None:
    for zone, citation in GOVERNMENT_ZONES:
        if domain == zone or domain.endswith(f".{zone}"):
            return Recognition(
                reason=Reason.GOVERNMENT_ZONE, bound_domain=domain,
                source_slug=f"zone:{zone}", source_url=citation,
            )
    return None


def name_variants(name: str) -> tuple[str, ...]:
    """The row's name and its bracketed or slashed alternative, casefolded.
    Used only to confirm a website a person already mapped (spec §13.8), never
    to find one."""
    base, _, bracket = name.partition(" (")
    parts = [base, bracket.rstrip(")"), *base.split(" / ")[1:]]
    return tuple(
        dict.fromkeys(" ".join(part.split()).casefold() for part in parts if len(part.strip()) >= 4)
    )


def verify_origin(entry: RegisterEntry, *, now: datetime, fetch: Fetch | None = None) -> str:
    fetch = fetch or fetch_page
    fetched = fetch(f"https://{entry.website_domain}/", purpose="provenance")
    if not usable(fetched):
        return f"not fetched ({fetched.outcome}: {fetched.reason})"
    if registrable_domain(fetched.final_url) != entry.website_domain:
        return f"redirected off the listed domain to {fetched.final_url}"
    text = " ".join(page_text(fetched.body).split()).casefold()
    if not any(variant in text for variant in name_variants(entry.name)):
        return "the page does not name the institution"
    entry.origin_verified_domain = entry.website_domain
    entry.origin_verified_at = now
    entry.save(update_fields=["origin_verified_domain", "origin_verified_at"])
    return "verified"


def verify_list_origins(
    slugs: Iterable[str], *, now: datetime, fetch: Fetch | None = None
) -> list[tuple[str, str, str]]:
    results: list[tuple[str, str, str]] = []
    entries = (
        RegisterEntry.objects.filter(register__in=list(slugs), resolution=RegisterEntry.Resolution.RESOLVED)
        .exclude(website_domain="")
        .order_by("register", "external_key")
    )
    for entry in entries:
        if entry.origin_verified_domain == entry.website_domain:
            results.append((entry.register, entry.external_key, "already verified"))
            continue
        results.append((entry.register, entry.external_key, verify_origin(entry, now=now, fetch=fetch)))
    return results
```

In `verify_origin`, `fetch or fetch_page` resolves `fetch_page` at call time. That is what lets the command test monkeypatch `apps.research.recognition.fetch_page`.

Create `apps/research/management/commands/verify_list_origins.py`:

```python
"""Confirm each reviewed closed-list row's website (spec §13.8).

A person mapped the website, often from search with the origin never fetched
(az_heis.csv says so row by row). The row counts as admission evidence only
once its origin answered on the listed domain and named the institution.
Operator-run, idempotent; failures are printed, never swallowed.
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.research.fetch import CATALOG_ROLE_NOTE
from apps.research.provenance import Reason
from apps.research.recognition import read_sources, verify_list_origins


class Command(BaseCommand):
    help = "Verify each reviewed closed-list row's website against its origin." + CATALOG_ROLE_NOTE

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--list", action="append", default=[], dest="slugs")

    def handle(self, *args: Any, **options: Any) -> None:
        slugs = options["slugs"] or [
            source.slug for source in read_sources() if source.role == Reason.CURATED_LIST
        ]
        for register, key, outcome in verify_list_origins(slugs, now=timezone.now()):
            self.stdout.write(f"{register} {key}: {outcome}")
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `POSTGRES_DB=tehsil_provenance_gate uv run pytest tests/research/test_recognition_lists.py tests/research/test_closed_lists.py tests/research/test_closed_list_data.py -q`
Expected: PASS.

- [ ] **Step 6: Run the four checks.**

- [ ] **Step 7: Commit**

```bash
git -C /home/orkhan/Desktop/provenance-gate add apps/research/recognition.py apps/research/closed_lists.py apps/research/management/commands/verify_list_origins.py docs/research/provenance-sources.csv docs/research/closed-lists.csv docs/research/closed-lists/national_scholarship_agencies.csv tests/research/test_recognition_lists.py
git -C /home/orkhan/Desktop/provenance-gate commit -m "feat(research): reviewed lists, funder lists and government zones as provenance evidence"
```

---

### Task 6: Country registers found through ENIC-NARIC, and the data-file transport

**Files:**
- Modify:
  - `apps/research/egress.py:16-24,254-336` (content types; per-call `max_bytes` on `fetch_data_file`)
  - `apps/research/recognition.py`
  - `docs/research/provenance-sources.csv`
  - `docs/research/closed-lists.csv`
- Test: `tests/research/test_provenance_registers.py`, `tests/research/test_egress.py`

**Interfaces:**
- Consumes:
  - `ProvenanceSource`, `read_sources`, `usable`, `list_recognitions`
  - `closed_lists.record_list`, `ListRow`, `ListReport`, `ListFileError`
  - `services.acquire_domain_lease`, `DomainBusy`
  - `storage.S3ObjectStore`, `snapshot.ObjectStore`
- Produces:
  - `egress.fetch_data_file(url, *, transport=..., require_https=False, sleep=..., max_bytes: int = MAX_RESPONSE_BYTES)`
  - `egress.ALLOWED_CONTENT_TYPES`, now including `application/rdap+json`, `text/csv`, `text/tab-separated-values` and the XLSX type
  - In `apps.research.recognition`:
    - `RegisterShape`, `RegisterNotVouched`, `RegisterUnreachable` (exceptions)
    - `RegisterRow(key: str, name: str, website: str)`
    - `enic_register_links(body: bytes) -> tuple[str, ...]`
    - `enic_vouches(source, spec: ClosedList, *, fetch=None) -> bool`
    - `parse_register(body: bytes, source: ProvenanceSource) -> tuple[RegisterRow, ...]`
    - `load_register(source, *, now: datetime, fetch=None, fetch_file=None, store: ObjectStore | None = None) -> ListReport`
    - `country_registers(country: str, sources) -> list[ProvenanceSource]`
    - `ensure_country_loaded(country: str, *, now: datetime, cycle: timedelta, sources, load=None, **load_kwargs) -> str`, returning `"ok" | "none" | "busy" | "failed"`
    - `register_state(country: str, sources) -> str`, returning `"absent" | "unbound_rows" | "not_loaded"`

Spec corrections for this task (measured 2026-09-26):

- **HRK Hochschulkompass is not shipped.** Its data file is `https://hs-kompass.de/kompass/xml/download/hs_liste.txt`: tab-separated, Latin-1, `text/plain`. Its imprint allows personal use only; "alle anderen Verwendungen, insbesondere die der kommerziellen Nutzung (auch einzelner Teile)" need the Stiftung's permission. German bodies stay `register_not_loaded` until permission is granted.
- **YÖK's recorded URL answered 404.** It is not shipped.
- **Korea needs no key.** Spec §13.7's blocker is void (coordinator, 2026-09-26, re-measured here). The standard-data download answers an anonymous GET with a JSON list of 1,995 rows (775,733 bytes). The rows are school, campus and graduate-school level, compiled by 한국대학교육협의회 with `CRTR_YMD` 2026-03-18, and 1,715 carry `HMPG_ADDR`. It is served as `text/html;charset=UTF-8`: `fetch_data_file` already allows that type, the source's `format` says how to parse it, and a body that is not JSON fails loudly as `RegisterShape`. `HMPG_ADDR` is a bare host, sometimes with a path (`kentech.ac.kr`, `homepage.cnu.ac.kr/cnuip`). Names repeat across campuses, so the row key is `SCHL_NM+MAINBRANCH_NM`. Cyber universities (사이버대학) stay in, because recognition is about the institution; online study is Plan 2's question.
- **Shipped registers.** Three ship:
  - The OfS Register: JSON at `https://register-api.officeforstudents.org.uk/api/Provider`, 473 providers, 1.59 MB. It is published under the OGL, and ENIC-NARIC's UK page links it.
  - SFC's funded-institution list: HTML, 19 institutions, OGL v3. It is named by hand, because ENIC-NARIC's UK page links gov.scot's policy page rather than a register.
  - Korea's university information dataset (#15107736): KOGL, named by hand.
- **TUM and METU are tested on fixtures.** Their known-answer tests use minimal captured samples and test-local source rows. KENTECH's runs on a captured sample of the shipped Korean source.

- [ ] **Step 1: Add the shipped register rows**

Append to `docs/research/provenance-sources.csv`:

```csv
gb_ofs_register,register,https://www.enic-naric.net/page-United-Kingdom,,https://register-api.officeforstudents.org.uk/api/Provider,json_list,utf-8,,LegalName,Website,Ukprn,UKPRN,,4000000
gb_sfc_universities,register,,"ENIC-NARIC's UK page links gov.scot's universities policy page, not a register; SFC's list of the universities it funds is Scotland's list of degree-awarding bodies (measured 2026-09-26)",https://www.sfc.ac.uk/our-funding/university-funding/,html_list,utf-8,,,,,,We currently provide funding to,
kr_univ_info,register,,"Korea is outside the ENIC-NARIC network; spec §5.1 names data.go.kr dataset #15107736 (university information, KOGL, compiled by 한국대학교육협의회); anonymous standard-data download, JSON served as text/html (measured 2026-09-26)",https://www.data.go.kr/download/standard.json?publicDataPk=15107736&colNmList=SCHL_NM&colNmList=SCHL_ENG_NM&colNmList=MAINBRANCH_NM&colNmList=UNIV_SE_NM&colNmList=SCHL_SE_NM&colNmList=FNDN_FORM_SE_NM&colNmList=CTPV_NM&colNmList=HMPG_ADDR&colNmList=FNDN_YMD&colNmList=CRTR_YMD&totalCount=1995&svcTableNm=tn_pubr_public_univ_info_svc&perPage=10000&page=1,json_list,utf-8,,SCHL_NM,HMPG_ADDR,SCHL_NM+MAINBRANCH_NM,,,3000000
```

Append to `docs/research/closed-lists.csv`:

```csv
gb_ofs_register,Office for Students -- the OfS Register (England),GB,INSTITUTION,1,https://www.officeforstudents.org.uk/for-providers/regulatory-resources/the-ofs-register/,Office for Students,no,yes,OPEN,https://www.officeforstudents.org.uk/copyright/,yes,ENUMERATE_ONLY,,2026-09-26
gb_sfc_universities,Scottish Funding Council -- funded universities and higher-education institutions,GB,INSTITUTION,1,https://www.sfc.ac.uk/our-funding/university-funding/,Scottish Funding Council,no,yes,OPEN,https://www.sfc.ac.uk/about-us/copyright/,yes,ENUMERATE_ONLY,19,2026-09-26
kr_univ_info,Ministry of Education -- university information (data.go.kr #15107736),KR,INSTITUTION,1,https://www.data.go.kr/data/15107736/standard.do,한국대학교육협의회 (Korean Council for University Education),no,yes,OPEN,https://www.data.go.kr/ugs/selectPublicDataUseGuideView.do,yes,ENUMERATE_ONLY,,2026-09-26
```

The `data_url` repeats the exact query the coordinator verified. `perPage=10000` returns all 1,995 rows on one page; if `totalCount` grows past `perPage`, the parse still succeeds, and the growth shows in the stored file. Both reference URLs in the Korean closed-list row (the dataset page and data.go.kr's use guide) answered 200 on 2026-09-26.

- [ ] **Step 2: Write the failing tests**

Append to `tests/research/test_egress.py`:

```python
def _resolve_public(monkeypatch) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda _host, port, *_args, **_kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))
        ],
    )


def test_the_byte_cap_is_per_call(monkeypatch) -> None:
    """Spec §6: a source's cap is its own; the default stays 10 MB."""
    _resolve_public(monkeypatch)
    with pytest.raises(ResponseTooLarge):
        fetch_data_file(
            "https://official.test/", max_bytes=5,
            transport=lambda _target, _path: FakeResponse(body=b"x" * 6),
        )
    assert fetch_data_file(
        "https://official.test/", max_bytes=6,
        transport=lambda _target, _path: FakeResponse(body=b"x" * 6),
    ).body == b"x" * 6


@pytest.mark.parametrize(
    "content_type",
    [
        "application/rdap+json",
        'application/rdap+json;extensions="rdap_level_0 jscontact";charset=UTF-8',
        "text/csv",
        "text/tab-separated-values",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ],
)
def test_register_and_rdap_types_are_data_files(monkeypatch, content_type: str) -> None:
    _resolve_public(monkeypatch)
    result = fetch_data_file(
        "https://official.test/",
        transport=lambda _target, _path: FakeResponse(headers={"Content-Type": content_type}),
    )
    assert result.body == b"official"
```

Create `tests/research/test_provenance_registers.py`:

```python
"""Country registers, found through ENIC-NARIC, read into the register (spec
§5.1 point 1, §6). Captured, minimal samples; no network."""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.research.egress import FetchResult
from apps.research.models import ClosedList, OrganisationDomain, RegisterEntry
from apps.research.recognition import (
    ProvenanceSource,
    RegisterNotVouched,
    RegisterShape,
    RegisterUnreachable,
    enic_register_links,
    ensure_country_loaded,
    list_recognitions,
    load_register,
    read_sources,
    register_state,
)
from tests.research.provenance_helpers import FakeFetch, FakeStore, make_body, make_list, page

pytestmark = pytest.mark.django_db
NOW = timezone.now()

ENIC_DE_URL = "https://www.enic-naric.net/page-Germany"
#: Shape captured from page-Germany 2026-09-26: one acc-group per section, the
#: heading in an h3, the links in a `content` div.
ENIC_GERMANY = """<html><body><div class="style2">
<div class="acc-group PL-NAZ"><div id="heading3"><a><h3 class="PL-NAZcont">Higher Education System</h3></a></div>
<div id="acc3" class="collapse"><div class="content PL-NAZcont"><p><a href="https://www.study-in-germany.de/en/">English</a></p></div></div></div>
<div class="acc-group PL-NAZ"><div id="heading4"><a><img alt="Recognised Higher Education Institutions"><h3 class="PL-NAZcont">Recognised Higher Education Institutions</h3></a></div>
<div id="acc4" class="collapse"><div class="content PL-NAZcont"><p><strong>Higher Education Compass</strong><br/>
<strong>Link(s):</strong> <a target="_blank" href="http://www.hochschulkompass.de/">German</a>, <a target="_blank" href="https://www.hochschulkompass.de/en/study-in-germany.html">English</a></p></div></div></div>
<div class="acc-group PL-NAZ"><div id="heading5"><a><h3 class="PL-NAZcont">Qualifications Framework</h3></a></div>
<div id="acc5" class="collapse"><div class="content PL-NAZcont"><p><a href="https://www.dqr.de/">DQR</a></p></div></div></div>
</div></body></html>"""

#: hs_liste.txt's real header names, three real rows, Latin-1 as served.
HRK_TSV = (
    "Hs-Nr.\tHochschulkurzname\tHochschulname\tHome Page\tMitglied HRK\n"
    "184\tMünchen TUM\tTechnische Universität München\thttp://www.tum.de\t1\n"
    "2\tAachen FH\tFachhochschule Aachen\thttp://www.fh-aachen.de\t1\n"
    "4\tAlbstadt-Sigmaringen H\tHochschule Albstadt-Sigmaringen\twww.hs-albsig.de\t1\n"
).encode("latin-1")
HRK = ProvenanceSource(
    slug="de_hochschulkompass", role="register", enic_naric_page=ENIC_DE_URL,
    data_url="https://hs-kompass.de/kompass/xml/download/hs_liste.txt", format="tsv",
    encoding="latin-1", name_field="Hochschulname", website_field="Home Page", id_field="Hs-Nr.",
    max_bytes=500_000,
)

SFC_URL = "https://www.sfc.ac.uk/our-funding/university-funding/"
SFC_HTML = """<html><body><header><ul><li><a href="https://twitter.com/sfc">Twitter</a></li></ul></header>
<div class="wysiwyg"><p>We currently provide funding to 19 universities and higher education institutions (HEIs).</p>
<ul><li><a title="this link opens in a new window" href="http://www.abertay.ac.uk">Abertay University</a></li>
<li><a href="http://www.ed.ac.uk">University of Edinburgh</a></li>
<li><a href="http://www.gla.ac.uk">University of Glasgow</a></li>
<li><a href="https://www.sfc.ac.uk/about-us/">About us</a></li></ul></div></body></html>"""
SFC = ProvenanceSource(
    slug="gb_sfc_universities", role="register", named_by_hand_because="test",
    data_url=SFC_URL, format="html_list", list_anchor="We currently provide funding to",
)

YOK_URL = "https://www.yok.gov.tr/universiteler/devlet-universiteleri"
YOK_HTML = """<html><body><h2>Devlet Üniversiteleri</h2><ul>
<li><a href="https://www.metu.edu.tr">Orta Doğu Teknik Üniversitesi</a></li>
<li><a href="https://www.itu.edu.tr">İstanbul Teknik Üniversitesi</a></li></ul></body></html>"""
YOK = ProvenanceSource(
    slug="tr_yok_register", role="register", named_by_hand_because="test",
    data_url=YOK_URL, format="html_list", list_anchor="Devlet Üniversiteleri",
)

#: Captured from data.go.kr's standard-data download for #15107736 on
#: 2026-09-26: a top-level JSON list, served as text/html. KENTECH appears
#: twice (university and graduate school, one site) and ROR lacks it.
KR_JSON = (
    '[{"SCHL_NM": "한국에너지공과대학교", "SCHL_ENG_NM": "Korea Institute of Energy Technology", '
    '"MAINBRANCH_NM": "본교", "SCHL_SE_NM": "대학교", "HMPG_ADDR": "www.kentech.ac.kr/"},'
    '{"SCHL_NM": "한국에너지공과대학교 대학원", "SCHL_ENG_NM": "Korea institute of Energy Technology", '
    '"MAINBRANCH_NM": "본교", "SCHL_SE_NM": "일반대학원", "HMPG_ADDR": "kentech.ac.kr"},'
    '{"SCHL_NM": "충남대학교 평화안보대학원", "SCHL_ENG_NM": "Graduate School Of Peace & Security '
    'Studies in Chungnam National University", "MAINBRANCH_NM": "본교", '
    '"SCHL_SE_NM": "특수대학원", "HMPG_ADDR": "peace.cnu.ac.kr/"},'
    '{"SCHL_NM": "어느대학교", "SCHL_ENG_NM": "", "MAINBRANCH_NM": "분교", '
    '"SCHL_SE_NM": "대학교", "HMPG_ADDR": ""}]'
).encode()

OFS_JSON = (
    b'[{"LegalName": "The University of Manchester", "Ukprn": "10007798", '
    b'"Website": "https://www.manchester.ac.uk", "EmailAddress": "x"},'
    b'{"LegalName": "Lamda Limited", "Ukprn": "10003758", "Website": "", "EmailAddress": "y"}]'
)
OFS = ProvenanceSource(
    slug="gb_ofs_register", role="register",
    enic_naric_page="https://www.enic-naric.net/page-United-Kingdom",
    data_url="https://register-api.officeforstudents.org.uk/api/Provider", format="json_list",
    name_field="LegalName", website_field="Website", id_field="Ukprn", id_scheme="UKPRN",
)


class FetchFile:
    def __init__(self, body: bytes, content_type: str = "text/plain") -> None:
        self.body, self.content_type, self.calls = body, content_type, []

    def __call__(self, url: str, **kwargs: object) -> FetchResult:
        self.calls.append((url, kwargs))
        return FetchResult(url, (), self.content_type, self.body)


def _germany() -> FakeFetch:
    return FakeFetch({ENIC_DE_URL: page(ENIC_DE_URL, ENIC_GERMANY)})


def test_only_the_recognised_institutions_section_counts() -> None:
    links = enic_register_links(ENIC_GERMANY.encode())
    assert links == (
        "http://www.hochschulkompass.de/",
        "https://www.hochschulkompass.de/en/study-in-germany.html",
    )


def test_tum_is_recognised_via_its_register_and_the_file_is_archived() -> None:
    make_list("de_hochschulkompass", country_code="DE",
              source_url="https://www.hochschulkompass.de/hochschulen/downloads.html")
    fetch_file, store = FetchFile(HRK_TSV), FakeStore()
    report = load_register(HRK, now=NOW, fetch=_germany(), fetch_file=fetch_file, store=store)
    assert (report.listed, report.bound) == (3, 3)
    assert fetch_file.calls[0][1]["max_bytes"] == 500_000
    assert list(store.objects.values()) == [HRK_TSV]
    body = OrganisationDomain.objects.get(registrable_domain="tum.de").organisation
    assert body.status == "REGISTERED"
    found, _ = list_recognitions(body, (HRK,))
    assert [(r.reason, r.bound_domain, r.country_code) for r in found] == [
        ("register", "tum.de", "DE")
    ]
    assert OrganisationDomain.objects.filter(registrable_domain="hs-albsig.de").exists()
    assert ClosedList.objects.get(slug="de_hochschulkompass").loaded_at == NOW


def test_a_register_enic_naric_does_not_link_is_not_read() -> None:
    make_list("de_hochschulkompass", country_code="DE",
              source_url="https://hochschulkompass-fake.com/list")
    with pytest.raises(RegisterNotVouched):
        load_register(HRK, now=NOW, fetch=_germany(), fetch_file=FetchFile(HRK_TSV), store=FakeStore())
    assert not RegisterEntry.objects.exists()


def test_a_register_whose_terms_are_not_open_is_not_read_by_code() -> None:
    make_list("de_hochschulkompass", country_code="DE", terms="UNREAD",
              source_url="https://www.hochschulkompass.de/hochschulen/downloads.html")
    with pytest.raises(RegisterNotVouched, match="OPEN"):
        load_register(HRK, now=NOW, fetch=_germany(), fetch_file=FetchFile(HRK_TSV), store=FakeStore())


def test_edinburgh_is_recognised_via_the_sfc_list_and_nothing_outside_the_list_is() -> None:
    make_list("gb_sfc_universities", country_code="GB", source_url=SFC_URL)
    load_register(SFC, now=NOW, fetch=FakeFetch({SFC_URL: page(SFC_URL, SFC_HTML)}), store=FakeStore())
    body = OrganisationDomain.objects.get(registrable_domain="ed.ac.uk").organisation
    found, _ = list_recognitions(body, (SFC,))
    assert [(r.reason, r.bound_domain) for r in found] == [("register", "ed.ac.uk")]
    assert not OrganisationDomain.objects.filter(registrable_domain="twitter.com").exists()
    assert not OrganisationDomain.objects.filter(registrable_domain="sfc.ac.uk").exists()


def test_metu_is_recognised_via_yok() -> None:
    make_list("tr_yok_register", country_code="TR", source_url=YOK_URL)
    load_register(YOK, now=NOW, fetch=FakeFetch({YOK_URL: page(YOK_URL, YOK_HTML)}), store=FakeStore())
    body = OrganisationDomain.objects.get(registrable_domain="metu.edu.tr").organisation
    assert [r.reason for r in list_recognitions(body, (YOK,))[0]] == ["register"]


def _korea():
    return next(source for source in read_sources() if source.slug == "kr_univ_info")


def test_kentech_is_recognised_via_the_korean_register_though_absent_from_ror() -> None:
    korea = _korea()
    make_list("kr_univ_info", country_code="KR", source_url="https://www.data.go.kr/data/15107736/standard.do")
    report = load_register(
        korea, now=NOW, fetch=FakeFetch({}), store=FakeStore(),
        fetch_file=FetchFile(KR_JSON, "text/html;charset=UTF-8"),
    )
    assert (report.listed, report.bound, report.unresolved) == (4, 3, 1)
    body = OrganisationDomain.objects.get(registrable_domain="kentech.ac.kr").organisation
    assert {r.reason for r in list_recognitions(body, (korea,))[0]} == {"register"}
    assert OrganisationDomain.objects.filter(registrable_domain="cnu.ac.kr").exists()


def test_a_json_register_whose_body_is_not_json_fails_loudly() -> None:
    make_list("kr_univ_info", country_code="KR")
    with pytest.raises(RegisterShape, match="not JSON"):
        load_register(
            _korea(), now=NOW, fetch=FakeFetch({}), store=FakeStore(),
            fetch_file=FetchFile(b"<html><body>maintenance</body></html>", "text/html"),
        )


def test_the_ofs_register_binds_by_website_and_keeps_the_ukprn() -> None:
    make_list("gb_ofs_register", country_code="GB",
              source_url="https://www.officeforstudents.org.uk/for-providers/regulatory-resources/the-ofs-register/")
    enic_uk = ('<div class="acc-group"><h3>Recognised Higher Education Institutions</h3>'
               '<div class="content"><a href="https://www.officeforstudents.org.uk/for-providers/'
               'regulatory-resources/the-ofs-register/#/">OfS</a></div></div>')
    report = load_register(
        OFS, now=NOW, fetch=FakeFetch({OFS.enic_naric_page: page(OFS.enic_naric_page, enic_uk)}),
        fetch_file=FetchFile(OFS_JSON, "application/json"), store=FakeStore(),
    )
    assert (report.bound, report.unresolved) == (1, 1)
    body = OrganisationDomain.objects.get(registrable_domain="manchester.ac.uk").organisation
    [recognition] = list_recognitions(body, (OFS,))[0]
    assert recognition.identifier == ("UKPRN", "10007798")


def test_a_page_without_the_list_anchor_fails_loudly() -> None:
    make_list("gb_sfc_universities", country_code="GB", source_url=SFC_URL)
    moved = SFC_HTML.replace("We currently provide funding to", "Our funded institutions")
    with pytest.raises(RegisterShape, match="anchor"):
        load_register(SFC, now=NOW, fetch=FakeFetch({SFC_URL: page(SFC_URL, moved)}), store=FakeStore())
    assert not RegisterEntry.objects.exists()


def test_zero_parsed_rows_is_a_shape_error_not_an_empty_register() -> None:
    make_list("gb_sfc_universities", country_code="GB", source_url=SFC_URL)
    empty = SFC_HTML.split("<ul><li><a title")[0] + "<ul></ul></div></body></html>"
    with pytest.raises(RegisterShape, match="no rows"):
        load_register(SFC, now=NOW, fetch=FakeFetch({SFC_URL: page(SFC_URL, empty)}), store=FakeStore())
    assert ClosedList.objects.get(slug="gb_sfc_universities").loaded_at is None


def test_a_printed_size_the_parse_does_not_reach_is_refused() -> None:
    make_list("gb_sfc_universities", country_code="GB", source_url=SFC_URL, printed_size=19)
    with pytest.raises(RegisterShape, match="prints 19"):
        load_register(SFC, now=NOW, fetch=FakeFetch({SFC_URL: page(SFC_URL, SFC_HTML)}), store=FakeStore())


def test_an_unreachable_html_register_is_unreachable_not_empty() -> None:
    make_list("gb_sfc_universities", country_code="GB", source_url=SFC_URL)
    with pytest.raises(RegisterUnreachable):
        load_register(SFC, now=NOW, fetch=FakeFetch({}), store=FakeStore())


def test_register_state() -> None:
    sources = (SFC,)
    assert register_state("GB", sources) == "not_loaded"
    assert register_state("JP", sources) == "not_loaded"
    spec = make_list("gb_sfc_universities", country_code="GB", source_url=SFC_URL)
    load_register(SFC, now=NOW, fetch=FakeFetch({SFC_URL: page(SFC_URL, SFC_HTML)}), store=FakeStore())
    assert register_state("GB", sources) == "absent"
    RegisterEntry.objects.create(
        register=spec.slug, external_key="name only", name="A College", resolution="UNRESOLVED",
        last_seen=NOW,
    )
    assert register_state("GB", sources) == "unbound_rows"


def test_ensure_country_loaded_reads_once_per_cycle_and_respects_the_lease() -> None:
    make_list("gb_sfc_universities", country_code="GB", source_url=SFC_URL)
    loads: list[str] = []

    def load(source, *, now, **_kwargs):
        loads.append(source.slug)
        ClosedList.objects.filter(slug=source.slug).update(loaded_at=now)

    cycle = timedelta(days=30)
    assert ensure_country_loaded("GB", now=NOW, cycle=cycle, sources=(SFC,), load=load) == "ok"
    assert ensure_country_loaded("GB", now=NOW, cycle=cycle, sources=(SFC,), load=load) == "ok"
    assert loads == ["gb_sfc_universities"]
    assert ensure_country_loaded("JP", now=NOW, cycle=cycle, sources=(SFC,), load=load) == "none"
    # Stale a cycle later, but the first load's 30-minute lease (taken on the
    # wall clock by acquire_domain_lease) is still held: a second loader waits.
    later = NOW + timedelta(days=31)
    assert ensure_country_loaded("GB", now=later, cycle=cycle, sources=(SFC,), load=load) == "busy"
    assert loads == ["gb_sfc_universities"]


def test_a_failed_load_is_failed_not_absent() -> None:
    make_list("gb_sfc_universities", country_code="GB", source_url=SFC_URL)

    def load(source, **_kwargs):
        raise RegisterUnreachable("sfc.ac.uk: DEAD")

    assert ensure_country_loaded("GB", now=NOW, cycle=timedelta(days=30), sources=(SFC,), load=load) == "failed"
    assert register_state("GB", (SFC,)) == "not_loaded"


def test_a_body_bound_before_the_load_is_the_one_the_register_binds() -> None:
    make_body("ed.ac.uk")
    make_list("gb_sfc_universities", country_code="GB", source_url=SFC_URL)
    load_register(SFC, now=NOW, fetch=FakeFetch({SFC_URL: page(SFC_URL, SFC_HTML)}), store=FakeStore())
    assert OrganisationDomain.objects.filter(registrable_domain="ed.ac.uk").count() == 1


def test_the_shipped_registers_are_open_and_linked_or_named_by_hand() -> None:
    registers = [source for source in read_sources() if source.role == "register"]
    assert {source.slug for source in registers} == {
        "gb_ofs_register", "gb_sfc_universities", "kr_univ_info",
    }
    for source in registers:
        assert source.enic_naric_page or source.named_by_hand_because
```

- [ ] **Step 3: Run them to verify they fail**

Run: `POSTGRES_DB=tehsil_provenance_gate uv run pytest tests/research/test_provenance_registers.py tests/research/test_egress.py -q --create-db`
Expected: FAIL with `ImportError: cannot import name 'RegisterShape'`, and `TypeError: fetch_data_file() got an unexpected keyword argument 'max_bytes'`.

- [ ] **Step 4: Implement the transport change**

In `apps/research/egress.py`, replace `ALLOWED_CONTENT_TYPES` with:

```python
ALLOWED_CONTENT_TYPES = {
    "application/json",
    "application/pdf",
    "application/xml",
    "text/html",
    "text/plain",
    "text/xml",
    # Institution provenance gate spec §6: registry RDAP answers, and
    # register files published as CSV/TSV/XLSX.
    "application/rdap+json",
    "text/csv",
    "text/tab-separated-values",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}
```

In `fetch_data_file`'s signature, add `max_bytes: int = MAX_RESPONSE_BYTES,` after `sleep`. In its read loop, replace `if size > MAX_RESPONSE_BYTES:` with `if size > max_bytes:`. Add one docstring sentence: "`max_bytes` is per call: a source's cap lives in its provenance-sources row; the 10 MB default is unchanged."

- [ ] **Step 5: Implement the loaders**

In `apps/research/recognition.py`, add these imports:

```python
import io
import json
from datetime import timedelta

import lxml.html

from .closed_lists import ListFileError, ListReport, ListRow, record_list
from .egress import FetchResult, SourceBlocked, fetch_data_file
from .services import DomainBusy, acquire_domain_lease
from .snapshot import ObjectStore
from .storage import S3ObjectStore
```

Also extend the `datetime` import to `from datetime import datetime, timedelta`, and merge `.egress` into one import line with `MAX_RESPONSE_BYTES`. Then append:

```python
class RegisterShape(ValueError):
    """A register that no longer reads the way its row says. Loud: loading
    nothing would read as every institution in the country absent."""


class RegisterNotVouched(RuntimeError):
    """Not linked from its ENIC-NARIC page, or not OPEN to be read by code."""


class RegisterUnreachable(RuntimeError):
    pass


@dataclass(frozen=True)
class RegisterRow:
    key: str
    name: str
    website: str


_ENIC_HEADING = "Recognised Higher Education Institutions"
LOAD_LEASE = timedelta(minutes=30)
FetchFile = Callable[..., FetchResult]


def enic_register_links(body: bytes) -> tuple[str, ...]:
    """Links in ENIC-NARIC's recognised-institutions section and only there
    (page-Germany / page-United-Kingdom shape, 2026-09-26). That section is the
    root of trust for WHICH list is official (spec §5.1)."""
    document = lxml.html.fromstring(body)
    groups = document.xpath(
        f'//div[contains(@class, "acc-group")][.//h3[normalize-space() = "{_ENIC_HEADING}"]]'
    )
    return tuple(
        str(href)
        for group in groups
        for href in group.xpath('.//div[contains(@class, "content")]//a/@href')
    )


def enic_vouches(source: ProvenanceSource, spec: ClosedList, *, fetch: Fetch | None = None) -> bool:
    fetched = (fetch or fetch_page)(source.enic_naric_page, purpose="provenance")
    if not usable(fetched):
        raise RegisterUnreachable(f"{source.enic_naric_page}: {fetched.outcome} {fetched.reason}")
    linked = {registrable_domain(link) for link in enic_register_links(fetched.body)}
    return registrable_domain(spec.source_url) in linked


def _key(row: dict[str, object], source: ProvenanceSource) -> str:
    """`id_field` may join several fields with "+": Korea's names repeat across
    campuses, so its key is SCHL_NM+MAINBRANCH_NM."""
    if not source.id_field:
        return ""
    return "|".join(str(row.get(field) or "").strip() for field in source.id_field.split("+"))


def _tsv(body: bytes, source: ProvenanceSource) -> list[RegisterRow]:
    reader = csv.DictReader(io.StringIO(body.decode(source.encoding)), delimiter="\t")
    wanted = {source.name_field, source.website_field} | (set(source.id_field.split("+")) - {""})
    missing = wanted - set(reader.fieldnames or ())
    if missing:
        raise RegisterShape(f"{source.slug}: columns {sorted(missing)} are absent")
    return [
        RegisterRow(
            key=_key(dict(row), source),
            name=(row.get(source.name_field) or "").strip(),
            website=(row.get(source.website_field) or "").strip(),
        )
        for row in reader
    ]


def _json_list(body: bytes, source: ProvenanceSource) -> list[RegisterRow]:
    """The format column decides the parse, not the Content-Type: Korea serves
    its JSON as text/html. A body that is not JSON is a shape error, loud."""
    try:
        data: object = json.loads(body.decode(source.encoding))
    except ValueError as error:
        raise RegisterShape(f"{source.slug}: the body is not JSON ({error})") from error
    for part in filter(None, source.records_path.split(".")):
        data = data.get(part) if isinstance(data, dict) else None
    if not isinstance(data, list):
        raise RegisterShape(f"{source.slug}: {source.records_path or 'the body'} is not a list")
    return [
        RegisterRow(
            key=_key(item, source),
            name=str(item.get(source.name_field) or "").strip(),
            website=str(item.get(source.website_field) or "").strip(),
        )
        for item in data
        if isinstance(item, dict)
    ]


def _html_list(body: bytes, source: ProvenanceSource) -> list[RegisterRow]:
    document = lxml.html.fromstring(body)
    anchors = document.xpath(
        "//*[contains(normalize-space(text()), $anchor)]", anchor=source.list_anchor
    )
    if not anchors:
        raise RegisterShape(f"{source.slug}: the list anchor {source.list_anchor!r} is not on the page")
    own = registrable_domain(source.data_url)
    links = anchors[0].xpath("following-sibling::*[self::ul or self::ol][1]/li/a[@href]")
    return [
        RegisterRow(key="", name=link.text_content().strip(), website=str(link.get("href")).strip())
        for link in links
        if registrable_domain(str(link.get("href"))) not in ("", own)
    ]


_PARSERS: dict[str, Callable[[bytes, ProvenanceSource], list[RegisterRow]]] = {
    "tsv": _tsv, "json_list": _json_list, "html_list": _html_list,
}


def parse_register(body: bytes, source: ProvenanceSource) -> tuple[RegisterRow, ...]:
    rows: dict[str, RegisterRow] = {}
    for row in _PARSERS[source.format](body, source):
        if row.name:
            rows.setdefault((row.key or row.name)[:120], row)
    if not rows:
        raise RegisterShape(
            f"{source.slug}: no rows parsed -- the publisher changed its format, and "
            "loading nothing would read as every institution absent"
        )
    return tuple(rows.values())


def _https(website: str) -> str:
    return website if not website or "//" in website else f"https://{website}"


def load_register(
    source: ProvenanceSource,
    *,
    now: datetime,
    fetch: Fetch | None = None,
    fetch_file: FetchFile | None = None,
    store: ObjectStore | None = None,
) -> ListReport:
    """Read one register into RegisterEntry rows through `record_list` -- the
    register's own website field is the binding (spec §5.2 rule 1)."""
    spec = ClosedList.objects.get(slug=source.slug)
    if spec.reuse_terms != ClosedList.Terms.OPEN:
        raise RegisterNotVouched(
            f"{source.slug}: reuse terms are {spec.reuse_terms}; only an OPEN register is read by code"
        )
    if source.enic_naric_page and not enic_vouches(source, spec, fetch=fetch):
        raise RegisterNotVouched(
            f"{source.slug}: {source.enic_naric_page} does not link {spec.source_url}"
        )
    if source.format == "html_list":
        fetched = (fetch or fetch_page)(source.data_url, purpose="provenance")
        if not usable(fetched):
            raise RegisterUnreachable(f"{source.slug}: {fetched.outcome} {fetched.reason}")
        body = fetched.body
    else:
        try:
            body = (fetch_file or fetch_data_file)(
                source.data_url, max_bytes=source.max_bytes, require_https=True
            ).body
        except SourceBlocked as error:
            raise RegisterUnreachable(f"{source.slug}: {error}") from error
    parsed = parse_register(body, source)
    if spec.printed_size and len(parsed) != spec.printed_size:
        raise RegisterShape(
            f"{source.slug}: parsed {len(parsed)} rows, the publisher prints {spec.printed_size}"
        )
    (store or S3ObjectStore()).put(f"registers/{source.slug}/{now:%Y-%m-%dT%H%M%S}", body)
    host_cells = (spec.country_code,) if spec.country_code else ("ANY",)
    rows = tuple(
        ListRow(
            external_key=(row.key or row.name)[:120], name=row.name[:300], kind="INSTITUTION",
            website=_https(row.website), page_url="", country_code=spec.country_code,
            home_cells=("ANY",), host_cells=host_cells, rejected_reason="",
            source_url=source.data_url, verified_on=now.date(),
        )
        for row in parsed
    )
    report = record_list(spec, rows, now=now)
    ClosedList.objects.filter(slug=spec.slug).update(loaded_at=now)
    return report


def country_registers(country: str, sources: Iterable[ProvenanceSource]) -> list[ProvenanceSource]:
    if not country:
        return []
    in_country = set(ClosedList.objects.filter(country_code=country).values_list("slug", flat=True))
    return [source for source in sources if source.role == Reason.REGISTER and source.slug in in_country]


def ensure_country_loaded(
    country: str,
    *,
    now: datetime,
    cycle: timedelta,
    sources: Iterable[ProvenanceSource],
    load: Callable[..., object] | None = None,
    **load_kwargs: object,
) -> str:
    """Load a country's registers when stale, one loader at a time (spec §7.1:
    two students reaching Germany at once cause one load)."""
    registers = country_registers(country, sources)
    if not registers:
        return "none"
    for source in registers:
        loaded_at = ClosedList.objects.values_list("loaded_at", flat=True).get(slug=source.slug)
        if loaded_at is not None and loaded_at > now - cycle:
            continue
        try:
            acquire_domain_lease(f"register:{source.slug}", interval=LOAD_LEASE)
        except DomainBusy:
            return "busy"
        try:
            (load or load_register)(source, now=now, **load_kwargs)
        except (RegisterShape, RegisterNotVouched, RegisterUnreachable, ListFileError) as error:
            logger.warning("register %s not loaded: %s", source.slug, error)
            return "failed"
    return "ok"


def register_state(country: str, sources: Iterable[ProvenanceSource]) -> str:
    """For a body no register names. "absent" only when every loaded row is
    bound: an unbound (name-only) row could be this body, so absence is not
    established and the answer is "unbound_rows" -> no_domain_binding."""
    slugs = [source.slug for source in country_registers(country, sources)]
    if not slugs or ClosedList.objects.filter(slug__in=slugs, loaded_at__isnull=True).exists():
        return "not_loaded"
    if RegisterEntry.objects.filter(
        register__in=slugs, resolution=RegisterEntry.Resolution.UNRESOLVED
    ).exists():
        return "unbound_rows"
    return "absent"
```

If mypy objects to `lxml.html` types, follow `apps/research/reader.py`, which imports `lxml.html` the same way. If reader.py carries a `# type: ignore`, copy it.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `POSTGRES_DB=tehsil_provenance_gate uv run pytest tests/research/test_provenance_registers.py tests/research/test_egress.py tests/research/test_recognition_lists.py tests/research/test_closed_list_data.py -q`
Expected: PASS.

- [ ] **Step 7: Run the four checks.**

- [ ] **Step 8: Commit**

```bash
git -C /home/orkhan/Desktop/provenance-gate add apps/research/egress.py apps/research/recognition.py docs/research/provenance-sources.csv docs/research/closed-lists.csv tests/research/test_provenance_registers.py tests/research/test_egress.py
git -C /home/orkhan/Desktop/provenance-gate commit -m "feat(research): country registers vouched by ENIC-NARIC, loaded under a lease"
```

---

### Task 7: ROR as an identifier binding and a country, never a name

**Files:**
- Modify: `apps/research/ror.py`, `apps/research/recognition.py`
- Test: `tests/research/test_ror_binding.py`

**Interfaces:**
- Consumes: `ror.by_domain`, `ror.website_link_domain`, `hosts.registrable_domain`, `RegisterEntry`, `ClosedList`.
- Produces:
  - `apps.research.ror.RorFacts(country_code: str = "", identifiers: frozenset[tuple[str, str]] = frozenset(), lookup_failed: bool = False)`
  - `apps.research.ror.ror_facts(domain: str, *, call: Call = fetch_json_api) -> RorFacts`
  - `apps.research.recognition.ror_recognitions(facts: RorFacts, domain: str, sources: Iterable[ProvenanceSource]) -> tuple[Recognition, ...]`

- [ ] **Step 1: Write the failing tests**

Create `tests/research/test_ror_binding.py`:

```python
"""ROR proves identity, never legitimacy (spec §2, §5.2 rule 2). It binds a
register row to our domain only through an identifier both carry."""

import pytest
from django.utils import timezone

from apps.research.egress import SourceBlocked
from apps.research.models import RegisterEntry
from apps.research.recognition import ProvenanceSource, ror_recognitions
from apps.research.ror import RorFacts, ror_facts
from tests.research.provenance_helpers import make_list

ESMT = {
    "id": "https://ror.org/03q6fxf40",
    "domains": ["esmt.org"],
    "links": [{"type": "website", "value": "https://esmt.berlin"}],
    "external_ids": [{"type": "wikidata", "all": ["Q1377512"], "preferred": "Q1377512"}],
    "locations": [{"geonames_details": {"country_code": "DE"}}],
}
NYENRODE = {
    "id": "https://ror.org/00dj5gm06",
    "domains": ["nyenrode.com"],
    "links": [{"type": "website", "value": "https://www.nyenrode.com"}],
    "locations": [{"geonames_details": {"country_code": "NL"}}],
}


def _call(*records):
    def call(url, *, params, headers):
        return {"items": list(records)}
    return call


def test_a_website_link_binds_even_when_domains_disagree() -> None:
    """ESMT's domains[] is esmt.org while its site is esmt.berlin -- 344 records
    disagree like this, so both are compared."""
    facts = ror_facts("esmt.berlin", call=_call(ESMT))
    assert facts.country_code == "DE"
    assert facts.identifiers == frozenset({("ROR", "03q6fxf40"), ("WIKIDATA", "Q1377512")})


def test_a_record_on_another_domain_binds_nothing() -> None:
    """Nyenrode is held under nyenrode.com; a body at nyenrode.nl is not it."""
    assert ror_facts("nyenrode.nl", call=_call(NYENRODE)) == RorFacts()


def test_a_failed_lookup_is_recorded_not_guessed() -> None:
    def broken(url, *, params, headers):
        raise SourceBlocked("api returned HTTP 503")

    assert ror_facts("tum.de", call=broken) == RorFacts(lookup_failed=True)


@pytest.mark.django_db
def test_a_register_row_with_a_shared_identifier_recognises_the_domain() -> None:
    make_list("de_register", country_code="DE", source_url="https://register.example.org/")
    RegisterEntry.objects.create(
        register="de_register", external_key="Q1377512", name="ESMT Berlin",
        resolution="UNRESOLVED", last_seen=timezone.now(),
    )
    sources = (ProvenanceSource(slug="de_register", role="register", id_scheme="WIKIDATA"),)
    facts = RorFacts(country_code="DE", identifiers=frozenset({("WIKIDATA", "Q1377512")}))
    [recognition] = ror_recognitions(facts, "esmt.berlin", sources)
    assert (recognition.reason, recognition.bound_domain, recognition.identifier) == (
        "register", "esmt.berlin", ("WIKIDATA", "Q1377512"),
    )
    assert recognition.admitted_via == "ror"
    assert recognition.country_code == "DE"


@pytest.mark.django_db
def test_no_shared_identifier_no_recognition() -> None:
    make_list("de_register", country_code="DE")
    RegisterEntry.objects.create(
        register="de_register", external_key="ESMT Berlin", name="ESMT Berlin",
        resolution="UNRESOLVED", last_seen=timezone.now(),
    )
    sources = (ProvenanceSource(slug="de_register", role="register", id_scheme="WIKIDATA"),)
    facts = RorFacts(identifiers=frozenset({("WIKIDATA", "Q1377512")}))
    assert ror_recognitions(facts, "esmt.berlin", sources) == ()
```

- [ ] **Step 2: Run them to verify they fail**

Run: `POSTGRES_DB=tehsil_provenance_gate uv run pytest tests/research/test_ror_binding.py -q --create-db`
Expected: FAIL with `ImportError: cannot import name 'RorFacts'`.

- [ ] **Step 3: Implement**

Append to `apps/research/ror.py`. Add `from .egress import SourceBlocked, fetch_json_api` (extending the existing import) and `from dataclasses import dataclass, field` if it is not already imported.

```python
@dataclass(frozen=True)
class RorFacts:
    """What ROR says about one domain, and only when a record's `domains[]` or
    `links[website]` IS that domain (spec §5.2 rule 2). Identity, never
    legitimacy: 7 of 13 unaccredited-list institutions are active ROR records."""

    country_code: str = ""
    identifiers: frozenset[tuple[str, str]] = field(default_factory=frozenset)
    lookup_failed: bool = False


#: ROR external-id types that name one of OrganisationIdentifier.SCHEMES.
_EXTERNAL_SCHEMES = {"wikidata": "WIKIDATA"}


def _country(record: dict[str, object]) -> str:
    for location in _list(record.get("locations")):
        if isinstance(location, dict) and isinstance(details := location.get("geonames_details"), dict):
            return str(details.get("country_code") or "").upper()
    return ""


def ror_facts(domain: str, *, call: Call = fetch_json_api) -> RorFacts:
    try:
        records = by_domain(domain, call=call)
    except (SourceBlocked, ValueError):
        return RorFacts(lookup_failed=True)
    for record in records:
        domains = {registrable_domain(str(value)) for value in _list(record.get("domains"))}
        if domain not in domains | {website_link_domain(record)}:
            continue
        identifiers: set[tuple[str, str]] = set()
        if record.get("id"):
            identifiers.add(("ROR", str(record["id"]).rstrip("/").rsplit("/", 1)[-1]))
        for external in _list(record.get("external_ids")):
            if isinstance(external, dict) and (scheme := _EXTERNAL_SCHEMES.get(str(external.get("type")))):
                identifiers |= {(scheme, str(value)) for value in _list(external.get("all"))}
        return RorFacts(country_code=_country(record), identifiers=frozenset(identifiers))
    return RorFacts()
```

In `apps/research/recognition.py`, add `from .ror import RorFacts` and append:

```python
def ror_recognitions(
    facts: RorFacts, domain: str, sources: Iterable[ProvenanceSource]
) -> tuple[Recognition, ...]:
    """A register row with no website, bound to `domain` because the row's
    identifier is one ROR carries for this exact domain. Never a name."""
    found: list[Recognition] = []
    registers = [source for source in sources if source.role == Reason.REGISTER and source.id_scheme]
    for scheme, value in sorted(facts.identifiers):
        slugs = [source.slug for source in registers if source.id_scheme == scheme]
        entry = RegisterEntry.objects.filter(register__in=slugs, external_key=value).first()
        if entry is None:
            continue
        spec = ClosedList.objects.get(slug=entry.register)
        found.append(
            Recognition(
                reason=Reason.REGISTER, bound_domain=domain, source_slug=entry.register,
                source_url=spec.source_url, list_date=spec.verified_on.isoformat(),
                country_code=spec.country_code, identifier=(scheme, value), admitted_via="ror",
            )
        )
    return tuple(found)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `POSTGRES_DB=tehsil_provenance_gate uv run pytest tests/research/test_ror_binding.py tests/research/test_ror.py -q`
Expected: PASS.

- [ ] **Step 5: Run the four checks.**

- [ ] **Step 6: Commit**

```bash
git -C /home/orkhan/Desktop/provenance-gate add apps/research/ror.py apps/research/recognition.py tests/research/test_ror_binding.py
git -C /home/orkhan/Desktop/provenance-gate commit -m "feat(research): ROR binds a register row by shared identifier and gives a country"
```

---

### Task 8: One Jev client, through OpenRouter

**Files:**
- Create: `apps/research/jev.py`
- Modify:
  - `apps/documents/research_fit/jev.py` (calls the shared client; the `JEV_URL`/`JEV_MODEL` constants are removed)
  - `config/settings/base.py` (`TYPESAFE_API_KEY` becomes `JEV_API_KEY`/`JEV_BASE_URL`/`JEV_MODEL`)
  - `tests/documents/research_fit/test_jev.py`, `tests/documents/research_fit/test_live.py`
- Test: `tests/research/test_jev_client.py`

**Interfaces:**
- Consumes: `egress.fetch_json_api`.
- Produces:
  - `apps.research.jev.JevUnavailable`
  - `apps.research.jev.JevReply(answers: dict[str, Any], model: str, input_tokens: int)`
  - `apps.research.jev.jev_url() -> str`
  - `apps.research.jev.ask(state: object, questions: Mapping[str, object], *, post=fetch_json_api, api_key: str | None = None) -> JevReply`
  - Settings `JEV_API_KEY` (env `OPENROUTER_API_KEY`), `JEV_BASE_URL` (default `https://openrouter.ai/api`), `JEV_MODEL` (default `jev-1.13`)

Spec correction (owner decision relayed 2026-09-26):

- **Jev is reached through OpenRouter's native System One route.** That is `POST {base}/v1/systemone`, with the same request shape as `api.typesafe.ai` and the OpenRouter key. It is not a chat-completions model. This replaces `TYPESAFE_API_KEY`.
- **The unexecuted decision-layer plan still uses the old names.** `docs/superpowers/plans/2026-09-23-decision-layer-and-rule-grammar.md` still names `TYPESAFE_API_KEY`/`TYPESAFE_MODEL`/`TYPESAFE_BASE_URL`. It takes these names when executed.

- [ ] **Step 1: Write the failing tests**

Create `tests/research/test_jev_client.py`:

```python
"""The one Jev client: OpenRouter's System One route, a pinned model, page text only."""

import os

import pytest
from django.conf import settings as django_settings

from apps.research.jev import JevUnavailable, ask, jev_url

QUESTIONS = {
    "s0": {
        "type": "noul",
        "instructions": {"question": "Does this sentence state a fee?", "inspect": "`sentences[0]`"},
    }
}


def _post(reply, sent):
    def post(url, *, payload, headers):
        sent.append({"url": url, "payload": payload, "headers": headers})
        return reply
    return post


def test_the_call_goes_to_openrouter_with_the_pinned_model(settings) -> None:
    settings.JEV_API_KEY = "k"
    sent: list[dict] = []
    reply = ask(
        {"sentences": ["An application fee of 50 EUR applies."]}, QUESTIONS,
        post=_post({"model": "typesafe/jev-1.13.0", "answers": {"s0": {"noul": 0.97}},
                    "usage": {"input_tokens": 40}}, sent),
    )
    assert sent[0]["url"] == "https://openrouter.ai/api/v1/systemone" == jev_url()
    assert sent[0]["headers"] == {"Authorization": "Bearer k"}
    assert sent[0]["payload"]["model"] == "jev-1.13"
    assert sent[0]["payload"]["state"] == {"sentences": ["An application fee of 50 EUR applies."]}
    assert (reply.answers, reply.model, reply.input_tokens) == (
        {"s0": {"noul": 0.97}}, "typesafe/jev-1.13.0", 40,
    )


def test_no_key_is_unavailable_and_nothing_is_sent(settings) -> None:
    settings.JEV_API_KEY = ""
    sent: list[dict] = []
    with pytest.raises(JevUnavailable, match="OPENROUTER_API_KEY"):
        ask({"sentences": []}, QUESTIONS, post=_post({}, sent))
    assert sent == []


def test_a_transport_failure_never_carries_the_key(settings) -> None:
    settings.JEV_API_KEY = "secret-key"

    def broken(url, *, payload, headers):
        raise RuntimeError(f"529 for {headers['Authorization']}")

    with pytest.raises(JevUnavailable) as raised:
        ask({"sentences": []}, QUESTIONS, post=broken)
    assert "secret-key" not in str(raised.value)


def test_a_reply_without_answers_is_unavailable(settings) -> None:
    settings.JEV_API_KEY = "k"
    with pytest.raises(JevUnavailable, match="no answers"):
        ask({"sentences": []}, QUESTIONS, post=_post({"model": "jev-1.13"}, []))


@pytest.mark.live
@pytest.mark.skipif(not os.getenv("OPENROUTER_API_KEY"), reason="OPENROUTER_API_KEY not set")
def test_live_openrouter_serves_the_pinned_jev_model() -> None:
    """Run by hand with -m live. Synthetic page text only; no student data."""
    reply = ask({"sentences": ["An application fee of 50 EUR applies."]}, QUESTIONS)
    assert django_settings.JEV_MODEL in reply.model
    assert 0.0 <= float(reply.answers["s0"]["noul"]) <= 1.0
```

In `tests/documents/research_fit/test_jev.py`:
- Replace the import line with `from apps.documents.research_fit.jev import JevClassifier, entity_by_pattern`.
- Add `from django.conf import settings as django_settings` and `from apps.research.jev import jev_url`.
- In `test_one_call_per_sentence_with_a_noul_and_a_choice`, change the two asserts to:

```python
    assert sent[0]["url"] == jev_url() and sent[0]["headers"] == {"Authorization": "Bearer k"}
    body = sent[0]["payload"]
    assert body["model"] == django_settings.JEV_MODEL and body["state"] == _SENTENCES[0]
```

- In `test_no_key_is_provider_unavailable`, change `settings.TYPESAFE_API_KEY = ""` to `settings.JEV_API_KEY = ""`.

In `tests/documents/research_fit/test_live.py`, change the skipif to `@pytest.mark.skipif(not os.getenv("OPENROUTER_API_KEY"), reason="OPENROUTER_API_KEY not set")`.

- [ ] **Step 2: Run them to verify they fail**

Run: `POSTGRES_DB=tehsil_provenance_gate uv run pytest tests/research/test_jev_client.py tests/documents/research_fit/test_jev.py -q --create-db`
Expected: FAIL with `ModuleNotFoundError: No module named 'apps.research.jev'`.

- [ ] **Step 3: Implement**

Create `apps/research/jev.py`:

```python
"""The one Jev (TypeSafe System One) client, reached through OpenRouter.

Owner decision 2026-09-26: `POST {JEV_BASE_URL}/v1/systemone` -- OpenRouter's
native route, the same request shape as api.typesafe.ai (a `state` and typed
`questions`), authenticated with the OpenRouter key. Not chat completions:
OpenRouter's `typesafe/jev-router` is a router over chat models, not Jev's
typed classifier. The model is a pinned versioned ID (`JEV_MODEL`, never
`jev-latest`), because a tuned threshold is pinned to the model that produced
it (2026-09-22 typed-decisions spec §3); the reply's `model` field names what
actually answered, and a caller that pins a threshold checks it.

Only page text is ever sent, never student data. Lives in apps.research
because apps.documents imports apps.research and never the reverse --
documents/research_fit/jev.py calls this rather than keeping a second client.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from django.conf import settings

from .egress import fetch_json_api


class JevUnavailable(RuntimeError):
    """No key, a transport failure, or a reply without answers."""


@dataclass(frozen=True)
class JevReply:
    answers: dict[str, Any]
    model: str
    input_tokens: int


def jev_url() -> str:
    return f"{settings.JEV_BASE_URL.rstrip('/')}/v1/systemone"


def ask(
    state: object,
    questions: Mapping[str, object],
    *,
    post: Callable[..., dict[str, object]] = fetch_json_api,
    api_key: str | None = None,
) -> JevReply:
    key = settings.JEV_API_KEY if api_key is None else api_key
    if not key:
        raise JevUnavailable("OPENROUTER_API_KEY is not set")
    try:
        data = post(
            jev_url(),
            payload={"state": state, "model": settings.JEV_MODEL, "questions": dict(questions)},
            headers={"Authorization": f"Bearer {key}"},
        )
    except Exception as error:  # noqa: BLE001 - any vendor failure is JevUnavailable
        # The type only: a transport message can echo request headers.
        raise JevUnavailable(f"jev call failed: {type(error).__name__}") from error
    answers = data.get("answers") if isinstance(data, dict) else None
    if not isinstance(answers, dict):
        raise JevUnavailable("jev reply had no answers")
    usage = data.get("usage")
    tokens = int(usage.get("input_tokens", 0)) if isinstance(usage, dict) else 0
    return JevReply(answers=answers, model=str(data.get("model") or ""), input_tokens=tokens)
```

In `apps/documents/research_fit/jev.py`:
- Delete the `JEV_URL` and `JEV_MODEL` constants.
- Add `from apps.research.jev import JevUnavailable, ask`.
- Set the constructor default key to `settings.JEV_API_KEY`.
- In `classify`, change the missing-key message to `"OPENROUTER_API_KEY is not set"`.
- Replace `_ask` with this complete method. The shape checks after `answers` are unchanged; `ask` now owns the URL, the key header, `model` and `state`:

```python
    def _ask(self, sentence: str, topic: str) -> tuple[float, str]:
        questions = {
            "relevant": {
                "type": "noul",
                "instructions": (
                    f"Does this sentence describe research or teaching work related to: "
                    f"{topic}?"
                ),
            },
            "kind": {
                "type": "choice",
                "instructions": "What does this sentence name?",
                "criteria": dict(_KIND_CRITERIA),
            },
        }
        try:
            reply = ask(sentence, questions, post=self._post, api_key=self._key)
        except JevUnavailable as error:
            raise ProviderUnavailable(str(error)) from error
        self.input_tokens += reply.input_tokens
        answers = reply.answers
        # A malformed vendor reply must degrade to ProviderUnavailable, never
        # propagate a raw AttributeError/ValueError -- this module must not
        # block a letter (D11).
        relevant_answer = answers.get("relevant")
        kind_answer = answers.get("kind")
        if not isinstance(relevant_answer, dict) or not isinstance(kind_answer, dict):
            raise ProviderUnavailable("jev reply had a malformed answer")
        try:
            relevant = float(relevant_answer.get("noul", 0.0))
        except (TypeError, ValueError) as error:
            raise ProviderUnavailable("jev reply had a non-numeric relevance") from error
        kind = kind_answer.get("choice", "none")
        return relevant, str(kind) if kind in KIND_VALUES else "none"
```

In `config/settings/base.py`, replace the `TYPESAFE_API_KEY` line and its comment with:

```python
#: Jev (TypeSafe System One) through OpenRouter (owner decision 2026-09-26):
#: `apps/research/jev.py` is the one client. The key is OpenRouter's, env only.
#: Only page text is ever sent to it; no real student text before the DPA.
JEV_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
JEV_BASE_URL = os.getenv("JEV_BASE_URL", "https://openrouter.ai/api")
#: A pinned, versioned model -- never the moving `jev-latest` alias. Every
#: Jev threshold in the repo is tuned against this ID.
JEV_MODEL = os.getenv("JEV_MODEL", "jev-1.13")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `POSTGRES_DB=tehsil_provenance_gate uv run pytest tests/research/test_jev_client.py tests/documents/research_fit -q`
Expected: PASS. The live test is deselected.

- [ ] **Step 5: Run the four checks.** `grep -rn TYPESAFE_API_KEY apps config tests` must print nothing.

- [ ] **Step 6: Commit**

```bash
git -C /home/orkhan/Desktop/provenance-gate add apps/research/jev.py apps/documents/research_fit/jev.py config/settings/base.py tests/research/test_jev_client.py tests/documents/research_fit/test_jev.py tests/documents/research_fit/test_live.py
git -C /home/orkhan/Desktop/provenance-gate commit -m "feat(research): one Jev client through OpenRouter, pinned model"
```

---

### Task 9: Blocking evidence and content vetoes

**Files:**
- Create:
  - `apps/research/blocking.py`
  - `apps/research/management/commands/mill_list_diff.py`
  - `docs/research/mill-list.csv`
  - `docs/research/accreditation-mills.csv`
- Modify: `config/settings/base.py`
- Test: `tests/research/test_blocking.py`

**Interfaces:**
- Consumes:
  - `provenance.ContentHit`, `provenance.MillHit`, `provenance.Reason`
  - `jev.ask`, `jev.JevUnavailable`
  - `ratelimit.rate_limited`, `harvest.page_text`
  - `closed_lists.DATA_DIR`
- Produces (all in `apps.research.blocking`):
  - `MILL_LIST`, `ACCREDITATION_MILLS: Path`
  - `MillRow(domain, name, country_code, source, source_revision)`
  - `read_mill_list(path=MILL_LIST) -> tuple[MillRow, ...]`
  - `mill_hit(domain: str, *, rows: Iterable[MillRow], register_countries: set[str]) -> MillHit | None`
  - `read_accreditors(path=ACCREDITATION_MILLS) -> tuple[str, ...]`
  - `sentences(text: str) -> list[str]`
  - `accreditation_hits(url: str, text: str, accreditors: Iterable[str]) -> tuple[ContentHit, ...]`
  - `fee_sentences(text) -> list[str]`, `degree_sentences(text) -> list[str]`
  - `VETO_THRESHOLD = 0.85`
  - `VetoSkipped`
  - `content_facts(pages: Sequence[tuple[str, str]], *, run_id: UUID, post=fetch_json_api, accreditors=None) -> tuple[tuple[ContentHit, ...], str]`
  - `body_page_texts(organisation, domain: str, *, store) -> list[tuple[str, str]]`
  - `wikipedia_entries(body: bytes) -> frozenset[str]`, `current_revision(body: bytes) -> str`, `revision_url(revision: str) -> str`
  - The `manage.py mill_list_diff` command
  - Setting `PROVENANCE_VETO_RUN_LIMIT` (default 400)

Spec correction for this task:

- **The mill list is a reviewed name→domain file.** Wikipedia's list carries names, not domains. The revision is pinned at 1376085262 (2026-09-22). Six rows ship, their domains verified by ROR on 2026-09-26: Bircham, Atlantic International, Warnborough, Irish International, Breyer State and American World University.
- **Seven known-answer mills wait for review.** St Clements (not found in ROR), Almeda, Rochville, Belford, Ashwood, Selinus (absent from the pinned revision) and Pacific Western (listed as "American Pacwest International University") are added by a person when their domains are checked. Their tests pin the mechanism with synthetic domains.
- **The accreditation-mill deny list is seeded from one pinned Wikipedia revision.** It takes 7 names from "List of unrecognized higher education accreditation organizations", revision 1375532752.

- [ ] **Step 1: Add the data**

Create `docs/research/mill-list.csv`:

```csv
domain,name,country_code,source,source_revision,verified_on
bircham.edu,Bircham International University,ES,wikipedia,1376085262,2026-09-26
aiu.edu,Atlantic International University,US,wikipedia,1376085262,2026-09-26
warnborough.ac.uk,Warnborough College,GB,wikipedia,1376085262,2026-09-26
iiu-edu.eu,Irish International University,IE,wikipedia,1376085262,2026-09-26
breyerstate.com,Breyer State University,PA,wikipedia,1376085262,2026-09-26
awuedu.org,American World University,US,wikipedia,1376085262,2026-09-26
```

The domains and countries come from each body's ROR record (bircham.edu `00q15w993`, aiu.edu `04j0w0694`, warnborough.ac.uk `0472ajt73`, iiu-edu.eu `057cchs06`, breyerstate.com `045v19n13`, awuedu.org `00vgj0470`). Each name appears on the pinned Wikipedia revision.

Create `docs/research/accreditation-mills.csv`:

```csv
name,source_url,source_revision,verified_on
World Association of Universities and Colleges,https://en.wikipedia.org/wiki/List_of_unrecognized_higher_education_accreditation_organizations,1375532752,2026-09-26
Central States Consortium of Colleges & Schools,https://en.wikipedia.org/wiki/List_of_unrecognized_higher_education_accreditation_organizations,1375532752,2026-09-26
Accreditation Council for Distance Education,https://en.wikipedia.org/wiki/List_of_unrecognized_higher_education_accreditation_organizations,1375532752,2026-09-26
Accreditation Council for Online Academia,https://en.wikipedia.org/wiki/List_of_unrecognized_higher_education_accreditation_organizations,1375532752,2026-09-26
Global Accreditation Commission,https://en.wikipedia.org/wiki/List_of_unrecognized_higher_education_accreditation_organizations,1375532752,2026-09-26
Board of Online Universities Accreditation,https://en.wikipedia.org/wiki/List_of_unrecognized_higher_education_accreditation_organizations,1375532752,2026-09-26
European Council for Distance and Open Learning,https://en.wikipedia.org/wiki/List_of_unrecognized_higher_education_accreditation_organizations,1375532752,2026-09-26
```

There is no allowlist. EQUIS, AMBA, AACSB and ABET are real accreditors and appear on no government list (spec §5.4 rule 2).

- [ ] **Step 2: Write the failing tests**

Create `tests/research/test_blocking.py`:

```python
"""BLOCKED needs positive evidence; content checks only veto (spec §5.4)."""

from io import StringIO
from pathlib import Path
from uuid import uuid4

import pytest
from django.core.management import call_command
from django.utils import timezone

from apps.funding.models import OfficialEvidenceClaim, OfficialSource, OfficialSourceSnapshot
from apps.research.blocking import (
    accreditation_hits,
    body_page_texts,
    content_facts,
    current_revision,
    degree_sentences,
    fee_sentences,
    mill_hit,
    read_accreditors,
    read_mill_list,
    revision_url,
    wikipedia_entries,
)
from tests.research.provenance_helpers import FakeFetch, FakeStore, evidence_program, make_body, page

FEE_RELEASE = "A processing fee of 150 USD must be paid to release your scholarship award."
APPLICATION_FEE = "An application fee of 50 EUR applies to all applicants."
APEL = "Credit for prior learning (APEL) lets you pay a fee to have experience assessed toward your degree."
DIPLOMA_SALE = "Order your accredited bachelor's degree today for a one-time payment of 299 USD."


def _jev(probabilities: dict[str, float], model: str = "typesafe/jev-1.13.0"):
    calls: list[dict] = []

    def post(url, *, payload, headers):
        calls.append(payload)
        listed = payload["state"]["sentences"]
        return {"model": model, "answers": {
            f"s{i}": {"type": "noul", "noul": probabilities.get(s, 0.0)} for i, s in enumerate(listed)
        }}

    post.calls = calls  # type: ignore[attr-defined]
    return post


def test_the_shipped_mill_list_blocks_the_ror_verified_mills_by_domain() -> None:
    rows = read_mill_list()
    domains = {row.domain for row in rows}
    assert {"bircham.edu", "aiu.edu", "warnborough.ac.uk", "iiu-edu.eu", "breyerstate.com",
            "awuedu.org"} <= domains
    hit = mill_hit("warnborough.ac.uk", rows=rows, register_countries=set())
    assert hit is not None and (hit.country_code, hit.overridden) == ("GB", False)
    assert {row.source_revision for row in rows if row.source == "wikipedia"} == {"1376085262"}


def test_only_the_mill_lists_own_country_can_override_it() -> None:
    rows = read_mill_list()
    assert mill_hit("warnborough.ac.uk", rows=rows, register_countries={"GB"}).overridden is True
    assert mill_hit("warnborough.ac.uk", rows=rows, register_countries={"SC"}).overridden is False
    assert mill_hit("tum.de", rows=rows, register_countries=set()) is None


@pytest.mark.parametrize(
    "name",
    ["St Clements University", "Almeda University", "Rochville University", "Belford University",
     "Ashwood University", "Selinus University", "Pacific Western University"],
)
def test_a_reviewed_mill_row_blocks_by_domain_never_by_name(tmp_path: Path, name: str) -> None:
    """The mechanism for the seven whose domains wait for review: a row blocks
    its DOMAIN; a body carrying the NAME on another domain is untouched."""
    domain = name.lower().replace(" ", "-") + "-fixture.com"
    path = tmp_path / "mill-list.csv"
    path.write_text(
        "domain,name,country_code,source,source_revision,verified_on\n"
        f"{domain},{name},US,wikipedia,1376085262,2026-09-26\n", encoding="utf-8",
    )
    rows = read_mill_list(path)
    assert mill_hit(domain, rows=rows, register_countries=set()) is not None
    assert mill_hit("real-university.edu", rows=rows, register_countries=set()) is None


def test_a_mill_row_that_is_not_a_registrable_domain_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "mill-list.csv"
    path.write_text(
        "domain,name,country_code,source,source_revision,verified_on\n"
        "www.bircham.edu,Bircham,ES,wikipedia,1,2026-09-26\n", encoding="utf-8",
    )
    with pytest.raises(ValueError, match="registrable"):
        read_mill_list(path)


def test_a_deny_listed_accreditor_is_picked_verbatim_by_code() -> None:
    accreditors = read_accreditors()
    hits = accreditation_hits(
        "https://diploma.example.com/about",
        "Our programmes are fully accredited by the World Association of Universities and Colleges.",
        accreditors,
    )
    assert [(hit.reason, hit.url) for hit in hits] == [
        ("accreditation_mill", "https://diploma.example.com/about")
    ]
    assert "World Association of Universities and Colleges" in hits[0].span


def test_real_accreditors_are_on_no_list_so_they_never_hit() -> None:
    text = "The school is accredited by EQUIS, AMBA and AACSB; its engineering degrees by ABET."
    assert accreditation_hits("https://esmt.berlin/", text, read_accreditors()) == ()


def test_the_pickers_choose_by_code_and_an_application_fee_is_not_picked() -> None:
    text = " ".join([FEE_RELEASE, APPLICATION_FEE, APEL, DIPLOMA_SALE])
    assert fee_sentences(text) == [FEE_RELEASE]
    assert APPLICATION_FEE not in degree_sentences(text)
    assert set(degree_sentences(text)) == {APEL, DIPLOMA_SALE}


def test_a_fee_to_release_an_award_is_a_hit(settings) -> None:
    settings.JEV_API_KEY = "k"
    post = _jev({FEE_RELEASE: 0.95})
    hits, status = content_facts(
        [("https://funder.example.com/award", FEE_RELEASE + " " + APPLICATION_FEE)],
        run_id=uuid4(), post=post, accreditors=(),
    )
    assert status == "run"
    assert [(hit.reason, hit.span) for hit in hits] == [("fee_to_release_award", FEE_RELEASE)]
    question = post.calls[0]["questions"]["s0"]
    assert question["type"] == "noul"
    assert question["instructions"]["inspect"] == "`sentences[0]`"
    assert set(question["criteria"]) == {"true", "false"}


def test_apel_wording_at_a_real_university_does_not_block(settings) -> None:
    settings.JEV_API_KEY = "k"
    hits, _ = content_facts(
        [("https://www.ox.ac.uk/", APEL)], run_id=uuid4(), post=_jev({APEL: 0.1}), accreditors=(),
    )
    assert hits == ()


def test_unconfigured_jev_is_skipped_recorded_and_never_called(settings) -> None:
    settings.JEV_API_KEY = ""
    post = _jev({FEE_RELEASE: 0.99})
    hits, status = content_facts(
        [("https://funder.example.com/", FEE_RELEASE)], run_id=uuid4(), post=post, accreditors=(),
    )
    assert (hits, status, post.calls) == ((), "skipped", [])


def test_a_different_served_model_means_the_threshold_does_not_apply(settings) -> None:
    settings.JEV_API_KEY = "k"
    hits, status = content_facts(
        [("https://funder.example.com/", FEE_RELEASE)], run_id=uuid4(),
        post=_jev({FEE_RELEASE: 0.99}, model="typesafe/jev-2.0.0"), accreditors=(),
    )
    assert (hits, status) == ((), "skipped")


def test_a_spent_run_limit_skips_rather_than_calls(settings) -> None:
    settings.JEV_API_KEY = "k"
    settings.PROVENANCE_VETO_RUN_LIMIT = 0
    post = _jev({FEE_RELEASE: 0.99})
    hits, status = content_facts(
        [("https://funder.example.com/", FEE_RELEASE)], run_id=uuid4(), post=post, accreditors=(),
    )
    assert (hits, status, post.calls) == ((), "skipped", [])


@pytest.mark.django_db
def test_the_bodys_own_stored_pages_are_what_the_vetoes_read() -> None:
    body = make_body("tum.de")
    program = evidence_program("https://www.tum.de/msc")
    claim = OfficialEvidenceClaim.objects.get(program=program)
    snapshot = OfficialSourceSnapshot.objects.create(
        source=OfficialSource.objects.get(canonical_url="https://www.tum.de/msc"),
        s3_key="official-sources/tum-msc", s3_version_id="1", sha256="c" * 64,
        final_url="https://www.tum.de/msc", redirect_chain=[], retrieved_at=timezone.now(),
        admissions_cycle="2027", content_type="text/html", byte_size=10,
    )
    OfficialEvidenceClaim.objects.filter(id=claim.id).update(snapshot=snapshot)
    store = FakeStore({"official-sources/tum-msc": b"<p>" + APEL.encode() + b"</p>"})
    assert body_page_texts(body, "tum.de", store=store) == [("https://www.tum.de/msc", APEL)]
    assert body_page_texts(body, "tum.de", store=FakeStore()) == []


PINNED = b"""<html><body><ul><li id="t-permalink"><a href="/w/index.php?title=List&amp;oldid=1376085262">Permanent link</a></li></ul>
<div class="mw-parser-output"><ul><li>Almeda University, Idaho[8]</li><li>Belford University</li></ul></div></body></html>"""
CURRENT = b"""<html><body><ul><li id="t-permalink"><a href="/w/index.php?title=List&amp;oldid=1380000000">Permanent link</a></li></ul>
<div class="mw-parser-output"><ul><li>Almeda University, Idaho[8]</li><li>New Mill University, Nowhere</li></ul></div></body></html>"""


def test_wikipedia_entries_and_revisions() -> None:
    assert current_revision(CURRENT) == "1380000000"
    assert wikipedia_entries(PINNED) - wikipedia_entries(CURRENT) >= {"Belford University"}
    assert "Almeda University, Idaho" in wikipedia_entries(PINNED)


def test_the_diff_command_shows_a_vandalised_or_real_edit(monkeypatch) -> None:
    from apps.research.management.commands import mill_list_diff

    monkeypatch.setattr(mill_list_diff, "fetch_page", FakeFetch({
        mill_list_diff.PAGE: page(mill_list_diff.PAGE, CURRENT),
        revision_url("1376085262"): page(revision_url("1376085262"), PINNED),
    }))
    out = StringIO()
    call_command("mill_list_diff", stdout=out)
    text = out.getvalue()
    assert "pinned 1376085262, current 1380000000" in text
    assert "+ New Mill University, Nowhere" in text
    assert "- Belford University" in text
```

- [ ] **Step 3: Run them to verify they fail**

Run: `POSTGRES_DB=tehsil_provenance_gate uv run pytest tests/research/test_blocking.py -q --create-db`
Expected: FAIL with `ModuleNotFoundError: No module named 'apps.research.blocking'`.

- [ ] **Step 4: Implement**

In `config/settings/base.py`, after `JEV_MODEL`:

```python
#: Jev calls one provenance_check run may make for the two content vetoes
#: (spec §5.4 rules 3-4): the cost circuit-breaker the LLM rule requires.
PROVENANCE_VETO_RUN_LIMIT = int(os.getenv("PROVENANCE_VETO_RUN_LIMIT", "400"))
```

Create `apps/research/blocking.py`:

```python
"""BLOCKED needs positive evidence; content checks may only veto (spec §5.4).

Rules 1-2 are code: a body's bound DOMAIN on a reviewed mill list, or a
deny-listed accreditor named verbatim on its page. Rules 3-4 are Jev yes/no
questions (through OpenRouter, apps/research/jev.py) on sentences picked by
code; with no key they are skipped and recorded as skipped. Nothing here can
admit a body: a hit lowers a verdict (decide(): a recognised body becomes
UNCONFIRMED(veto_conflict), an unrecognised one BLOCKED), a miss admits nothing.
"""

from __future__ import annotations

import csv
import logging
import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from uuid import UUID

import lxml.html
from django.conf import settings
from django.db.models import Q

from apps.funding.models import OfficialEvidenceClaim, OfficialSourceSnapshot
from apps.ratelimit import rate_limited

from .closed_lists import DATA_DIR
from .egress import fetch_json_api
from .harvest import page_text
from .hosts import registrable_domain
from .jev import JevUnavailable, ask
from .models import Organisation
from .provenance import ContentHit, MillHit, Reason

logger = logging.getLogger(__name__)

MILL_LIST = DATA_DIR / "mill-list.csv"
ACCREDITATION_MILLS = DATA_DIR / "accreditation-mills.csv"
_MILL_COLUMNS = ("domain", "name", "country_code", "source", "source_revision", "verified_on")
_ACCREDITOR_COLUMNS = ("name", "source_url", "source_revision", "verified_on")

#: The typed-decisions spec's band for "actions that cost" (§3.1a), pinned to
#: settings.JEV_MODEL: a reply from any other model is skipped, never scored.
VETO_THRESHOLD = 0.85
MAX_VETO_SENTENCES = 10
MAX_VETO_PAGES = 5


@dataclass(frozen=True)
class MillRow:
    domain: str
    name: str
    country_code: str
    source: str
    source_revision: str


def _csv(path: Path, columns: tuple[str, ...]) -> list[tuple[str, dict[str, str]]]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != columns:
            raise ValueError(f"{path.name}: columns {reader.fieldnames} are not {columns}")
        return [
            (f"{path.name}:{line}", {k: (v or "").strip() for k, v in row.items()})
            for line, row in enumerate(reader, start=2)
        ]


def read_mill_list(path: Path = MILL_LIST) -> tuple[MillRow, ...]:
    rows: list[MillRow] = []
    for where, row in _csv(path, _MILL_COLUMNS):
        if registrable_domain(row["domain"]) != row["domain"]:
            raise ValueError(f"{where}: {row['domain']!r} is not a registrable domain")
        rows.append(
            MillRow(row["domain"], row["name"], row["country_code"].upper(), row["source"],
                    row["source_revision"])
        )
    return tuple(rows)


def mill_hit(
    domain: str, *, rows: Iterable[MillRow], register_countries: set[str]
) -> MillHit | None:
    """By DOMAIN, never by name. Only a register of the country the mill list
    itself names overrides it (spec §5.4 rule 1)."""
    for row in rows:
        if row.domain == domain:
            return MillHit(
                source=row.source, revision=row.source_revision, country_code=row.country_code,
                overridden=row.country_code in register_countries,
            )
    return None


def read_accreditors(path: Path = ACCREDITATION_MILLS) -> tuple[str, ...]:
    return tuple(row["name"].casefold() for _where, row in _csv(path, _ACCREDITOR_COLUMNS))


_SENTENCE_BREAK = re.compile(r"(?<=[.!?])\s+|\n+")
_ACCREDIT = re.compile(r"accredit|akkredit|akredit|accrédit", re.IGNORECASE)
_MONEY = re.compile(r"\bfees?\b|\bpay(?:ment|able)?\b|\bcharge\b|€|\$|£|\b(?:usd|eur|gbp)\b", re.IGNORECASE)
_AWARD = re.compile(r"scholarship|award|grant|stipend|bursary", re.IGNORECASE)
_RELEASE = re.compile(r"release|receive|disburse|claim|transfer|activate", re.IGNORECASE)
_DEGREE = re.compile(r"\bdegree|diploma|doctorate|\bph\.?d\b|master'?s|bachelor'?s", re.IGNORECASE)
_PURCHASE = re.compile(r"\bbuy\b|purchase|\border\b|\bprice\b|\bpay\b|payment|\bfee\b", re.IGNORECASE)


def sentences(text: str) -> list[str]:
    return [part.strip() for part in _SENTENCE_BREAK.split(text) if len(part.strip()) > 20]


def accreditation_hits(url: str, text: str, accreditors: Iterable[str]) -> tuple[ContentHit, ...]:
    names = tuple(accreditors)
    hits: list[ContentHit] = []
    for sentence in sentences(text):
        if not _ACCREDIT.search(sentence):
            continue
        lowered = sentence.casefold()
        if any(name in lowered for name in names):
            hits.append(ContentHit(Reason.ACCREDITATION_MILL, sentence[:300], url))
    return tuple(hits)


def fee_sentences(text: str) -> list[str]:
    return [
        s for s in sentences(text) if _MONEY.search(s) and _AWARD.search(s) and _RELEASE.search(s)
    ][:MAX_VETO_SENTENCES]


def degree_sentences(text: str) -> list[str]:
    return [s for s in sentences(text) if _DEGREE.search(s) and _PURCHASE.search(s)][:MAX_VETO_SENTENCES]


@dataclass(frozen=True)
class _Veto:
    reason: str
    question: str
    criteria: dict[str, str]
    pick: Callable[[str], list[str]]


#: One judgment per question, high means yes, {true, false} criteria because
#: the boundary cases are known (typed-decisions spec §3.1a): an ordinary
#: application fee, and credit for prior learning.
_VETOES = (
    _Veto(
        Reason.FEE_TO_RELEASE_AWARD,
        "Does this sentence demand a payment from the recipient in order to receive or "
        "release a scholarship or award?",
        {
            "true": "A fee, deposit or charge the recipient must pay before an awarded "
                    "scholarship is paid out, released, transferred or activated.",
            "false": "An ordinary application fee for applying, tuition, or a cost the "
                     "scholarship itself covers.",
        },
        fee_sentences,
    ),
    _Veto(
        Reason.DEGREE_FOR_PAYMENT,
        "Does this sentence offer a degree or diploma in exchange for payment with no study "
        "required?",
        {
            "true": "A degree, diploma or transcript sold for a fee, or granted on payment "
                    "alone without courses or assessment.",
            "false": "Credit for prior learning (APEL or RPL) counted toward a degree the "
                     "student still studies for, or tuition for a taught programme.",
        },
        degree_sentences,
    ),
)


class VetoSkipped(RuntimeError):
    pass


def _veto_hits(
    url: str, picked: list[str], veto: _Veto, *, post: Callable[..., dict[str, object]], run_id: UUID
) -> list[ContentHit]:
    if not picked:
        return []
    if rate_limited(
        "provenance-veto", run_id, limit=settings.PROVENANCE_VETO_RUN_LIMIT, window_seconds=86_400
    ):
        raise VetoSkipped("this run's Jev call limit is spent")
    questions = {
        f"s{index}": {
            "type": "noul",
            "instructions": {"question": veto.question, "inspect": f"`sentences[{index}]`"},
            "criteria": veto.criteria,
        }
        for index in range(len(picked))
    }
    try:
        reply = ask({"sentences": picked}, questions, post=post)
    except JevUnavailable as error:
        raise VetoSkipped(str(error)) from error
    if settings.JEV_MODEL not in reply.model:
        raise VetoSkipped(
            f"served {reply.model or 'an unnamed model'}; the threshold is pinned to "
            f"{settings.JEV_MODEL}"
        )
    hits: list[ContentHit] = []
    for index, sentence in enumerate(picked):
        answer = reply.answers.get(f"s{index}")
        try:
            probability = float(answer["noul"]) if isinstance(answer, dict) else None
        except (KeyError, TypeError, ValueError):
            probability = None
        if probability is None:
            raise VetoSkipped(f"no usable answer for sentence {index}")
        if probability >= VETO_THRESHOLD:
            hits.append(ContentHit(veto.reason, sentence[:300], url))
    return hits


def content_facts(
    pages: Sequence[tuple[str, str]],
    *,
    run_id: UUID,
    post: Callable[..., dict[str, object]] = fetch_json_api,
    accreditors: Iterable[str] | None = None,
) -> tuple[tuple[ContentHit, ...], str]:
    """(hits, "run" | "skipped"). Rule 2 always runs; rules 3-4 need Jev."""
    names = tuple(accreditors) if accreditors is not None else read_accreditors()
    hits: list[ContentHit] = []
    status = "run" if settings.JEV_API_KEY else "skipped"
    for url, text in pages:
        hits.extend(accreditation_hits(url, text, names))
        if not settings.JEV_API_KEY:
            continue
        for veto in _VETOES:
            try:
                hits.extend(_veto_hits(url, veto.pick(text), veto, post=post, run_id=run_id))
            except VetoSkipped as error:
                logger.info("provenance veto %s skipped for %s: %s", veto.reason, url, error)
                status = "skipped"
    return tuple(hits), status


class ObjectReader(Protocol):
    def get(self, key: str) -> bytes: ...


def body_page_texts(
    organisation: Organisation, domain: str, *, store: ObjectReader
) -> list[tuple[str, str]]:
    """The body's own archived pages -- its programmes' and awards' evidence
    snapshots, newest first -- read from the evidence bucket, never re-fetched."""
    snapshot_ids = (
        OfficialEvidenceClaim.objects.filter(
            Q(program__evidence_domain=domain) | Q(fundingopportunity__organisation=organisation)
        )
        .exclude(snapshot=None)
        .values("snapshot")
    )
    pages: list[tuple[str, str]] = []
    for snapshot in OfficialSourceSnapshot.objects.filter(id__in=snapshot_ids).order_by(
        "-retrieved_at"
    )[:MAX_VETO_PAGES]:
        try:
            body = store.get(snapshot.s3_key)
        except KeyError:
            logger.warning("snapshot %s is missing from the evidence bucket", snapshot.s3_key)
            continue
        pages.append((snapshot.final_url, page_text(body)))
    return pages


WIKIPEDIA_TITLE = "List_of_unaccredited_institutions_of_higher_education"
_REFERENCE = re.compile(r"\[\d+\]")


def revision_url(revision: str) -> str:
    return f"https://en.wikipedia.org/w/index.php?title={WIKIPEDIA_TITLE}&oldid={revision}"


def current_revision(body: bytes) -> str:
    match = re.search(rb'id="t-permalink".*?oldid=(\d+)', body, re.DOTALL)
    if match is None:
        raise ValueError("no permanent-link revision on the page")
    return match.group(1).decode()


def wikipedia_entries(body: bytes) -> frozenset[str]:
    """Entry names, reference markers stripped. Navigation items appear in both
    revisions of a diff and cancel out."""
    document = lxml.html.fromstring(body)
    return frozenset(
        _REFERENCE.sub("", " ".join(item.text_content().split()))[:200]
        for item in document.xpath('//div[contains(@class, "mw-parser-output")]//li')
        if len(item.text_content().strip()) > 3
    )
```

Create `apps/research/management/commands/mill_list_diff.py`:

```python
"""Diff the pinned Wikipedia mill list against today's revision (spec §5.4).

The list is pinned by revision in docs/research/mill-list.csv. A new or removed
entry is printed for the operator, so a vandalised edit is visible, and a
person maps any new mill to its DOMAIN in that file, then moves the revision.
Nothing here writes a row: the list is a reviewed diff, never a name match.
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandError

from apps.research.blocking import (
    WIKIPEDIA_TITLE,
    current_revision,
    read_mill_list,
    revision_url,
    wikipedia_entries,
)
from apps.research.fetch import CATALOG_ROLE_NOTE, fetch_page
from apps.research.recognition import usable

PAGE = f"https://en.wikipedia.org/wiki/{WIKIPEDIA_TITLE}"


class Command(BaseCommand):
    help = "Show entries added to or removed from the pinned Wikipedia mill list." + CATALOG_ROLE_NOTE

    def handle(self, *args: Any, **options: Any) -> None:
        pinned = max(
            (row.source_revision for row in read_mill_list() if row.source == "wikipedia"), key=int
        )
        current_page = fetch_page(PAGE, purpose="provenance")
        if not usable(current_page):
            raise CommandError(f"{PAGE}: {current_page.outcome} {current_page.reason}")
        current = current_revision(current_page.body)
        if current == pinned:
            self.stdout.write(f"unchanged at revision {pinned}")
            return
        pinned_page = fetch_page(revision_url(pinned), purpose="provenance")
        if not usable(pinned_page):
            raise CommandError(f"revision {pinned}: {pinned_page.outcome} {pinned_page.reason}")
        before, after = wikipedia_entries(pinned_page.body), wikipedia_entries(current_page.body)
        self.stdout.write(f"pinned {pinned}, current {current}")
        for name in sorted(after - before):
            self.stdout.write(f"+ {name}")
        for name in sorted(before - after):
            self.stdout.write(f"- {name}")
        self.stdout.write(
            "Review these names; map any new mill to its domain in docs/research/mill-list.csv "
            "and move source_revision to the new revision."
        )
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `POSTGRES_DB=tehsil_provenance_gate uv run pytest tests/research/test_blocking.py -q`
Expected: PASS.

- [ ] **Step 6: Run the four checks.**

- [ ] **Step 7: Commit**

```bash
git -C /home/orkhan/Desktop/provenance-gate add apps/research/blocking.py apps/research/management/commands/mill_list_diff.py docs/research/mill-list.csv docs/research/accreditation-mills.csv config/settings/base.py tests/research/test_blocking.py
git -C /home/orkhan/Desktop/provenance-gate commit -m "feat(research): mill list, accreditation mills and Jev vetoes that only lower a verdict"
```

---

### Task 10: Vouching by link, one hop, part-of only

**Files:**
- Create: `apps/research/vouch.py`
- Test: `tests/research/test_vouch.py`

**Interfaces:**
- Consumes: `fetch.fetch_page`, `recognition.usable`, `hosts.registrable_domain`, `provenance.Reason`.
- Produces (all in `apps.research.vouch`):
  - `STRUCTURAL_TERMS`, `EXCLUDED_TERMS: tuple[str, ...]`
  - `MAX_STRUCTURAL_PAGES = 10`
  - `VouchResult(vouch_url: str = "", recogniser_domain: str = "", failed: bool = False)`
  - `find_vouch(candidate: str, recognisers: Mapping[str, str], *, fetch=None) -> VouchResult`, where `recognisers` maps each RECOGNISED body's bound domain to its reason code

- [ ] **Step 1: Write the failing tests**

Create `tests/research/test_vouch.py`:

```python
"""A body no authority names is RECOGNISED(vouched_by_link) only by its
recogniser's own structural link to it (spec §5.3). UFAZ is the case."""

from apps.research.vouch import EXCLUDED_TERMS, STRUCTURAL_TERMS, find_vouch
from tests.research.provenance_helpers import FakeFetch, page

UFAZ = "https://ufaz.az/"
ASOIU = "https://asoiu.edu.az/"
UFAZ_HOME = '<html><body><h1>UFAZ</h1><footer><a href="https://asoiu.edu.az/">ASOIU</a></footer></body></html>'
#: The measured shape (asoiu.edu.az, 2026-09-26): the UFAZ link sits in
#: header > nav > ... > ul.top, beside a dual-degree programme link.
ASOIU_HOME = """<html><head><title>ASOIU |</title></head><body><header>
<nav class="scroll_nav navigations"><div id="nav"><ul class="top">
<li><a href="/warwick">Vorvik İkili Diplom Proqramı</a></li>
<li><a href="https://www.ufaz.az/en/">UFAZ</a></li></ul></div></nav></header>
<main><p>News</p></main></body></html>"""
RECOGNISERS = {"asoiu.edu.az": "curated_list"}


def test_ufaz_is_vouched_by_asoius_navigation() -> None:
    fetch = FakeFetch({UFAZ: page(UFAZ, UFAZ_HOME), ASOIU: page(ASOIU, ASOIU_HOME)})
    result = find_vouch("ufaz.az", RECOGNISERS, fetch=fetch)
    assert (result.vouch_url, result.recogniser_domain, result.failed) == (ASOIU, "asoiu.edu.az", False)


def test_a_structural_page_within_two_hops_vouches() -> None:
    home = """<html><body><main><a href="/structure">Faculties and institutes</a>
<a href="https://www.ufaz.az/">UFAZ news item</a></main></body></html>"""
    structure = '<html><body><h1>Faculties</h1><a href="https://www.ufaz.az/">UFAZ</a></body></html>'
    fetch = FakeFetch({
        UFAZ: page(UFAZ, UFAZ_HOME), ASOIU: page(ASOIU, home),
        "https://asoiu.edu.az/structure": page("https://asoiu.edu.az/structure", structure),
    })
    assert find_vouch("ufaz.az", RECOGNISERS, fetch=fetch).vouch_url == "https://asoiu.edu.az/structure"


def test_a_partners_page_never_vouches() -> None:
    home = '<html><body><main><a href="/structure">Faculties</a></main></body></html>'
    partners = '<html><body><h1>Partner universities</h1><a href="https://www.ufaz.az/">UFAZ</a></body></html>'
    fetch = FakeFetch({
        UFAZ: page(UFAZ, UFAZ_HOME), ASOIU: page(ASOIU, home),
        "https://asoiu.edu.az/structure": page("https://asoiu.edu.az/structure", partners),
    })
    assert find_vouch("ufaz.az", RECOGNISERS, fetch=fetch).vouch_url == ""


def test_a_link_on_a_user_subdomain_never_vouches() -> None:
    home = '<html><body><main><a href="https://blog.asoiu.edu.az/faculties">Faculties</a></main></body></html>'
    blog = '<html><body><h1>Faculties</h1><a href="https://www.ufaz.az/">UFAZ</a></body></html>'
    fetch = FakeFetch({
        UFAZ: page(UFAZ, UFAZ_HOME), ASOIU: page(ASOIU, home),
        "https://blog.asoiu.edu.az/faculties": page("https://blog.asoiu.edu.az/faculties", blog),
    })
    assert find_vouch("ufaz.az", RECOGNISERS, fetch=fetch).vouch_url == ""
    assert "https://blog.asoiu.edu.az/faculties" not in fetch.calls


def test_a_recogniser_that_redirects_off_its_host_vouches_for_nothing() -> None:
    fetch = FakeFetch({
        UFAZ: page(UFAZ, UFAZ_HOME),
        ASOIU: page(ASOIU, ASOIU_HOME, final_url="https://parked-domains.com/lander"),
    })
    assert find_vouch("ufaz.az", RECOGNISERS, fetch=fetch).vouch_url == ""


def test_a_body_admitted_by_link_vouches_for_nothing() -> None:
    fetch = FakeFetch({UFAZ: page(UFAZ, UFAZ_HOME), ASOIU: page(ASOIU, ASOIU_HOME)})
    assert find_vouch("ufaz.az", {"asoiu.edu.az": "vouched_by_link"}, fetch=fetch).vouch_url == ""


def test_a_recogniser_is_chosen_by_the_candidates_link_never_by_a_name() -> None:
    """ASOIU links UFAZ, but UFAZ's own page does not link ASOIU: nothing to
    follow, and ASOIU is never fetched."""
    silent = "<html><body><h1>UFAZ, part of ASOIU</h1></body></html>"
    fetch = FakeFetch({UFAZ: page(UFAZ, silent), ASOIU: page(ASOIU, ASOIU_HOME)})
    assert find_vouch("ufaz.az", RECOGNISERS, fetch=fetch).vouch_url == ""
    assert fetch.calls == [UFAZ]


def test_the_structural_crawl_is_bounded() -> None:
    home = "<html><body><main>" + "".join(
        f'<a href="/faculty-{n}">Faculty {n}</a>' for n in range(25)
    ) + "</main></body></html>"
    fetch = FakeFetch({UFAZ: page(UFAZ, UFAZ_HOME), ASOIU: page(ASOIU, home)})
    find_vouch("ufaz.az", RECOGNISERS, fetch=fetch)
    assert len(fetch.calls) <= 2 + 10


def test_an_unreachable_candidate_is_a_failed_lookup() -> None:
    assert find_vouch("ufaz.az", RECOGNISERS, fetch=FakeFetch({})).failed is True


def test_the_term_lists_are_pinned() -> None:
    assert STRUCTURAL_TERMS == (
        "faculties", "faculty", "schools", "institutes", "campuses", "branches",
        "affiliated institutions",
        "fakültələr", "fakültə", "institutlar", "filiallar", "kampuslar",
        "fakülteler", "enstitüler", "yüksekokullar", "kampüsler",
        "fakultäten", "fachbereiche", "institute", "standorte",
        "facultés", "écoles", "instituts", "composantes",
        "단과대학", "대학원", "캠퍼스", "부속기관",
    )
    assert EXCLUDED_TERMS == (
        "partners", "partner", "agents", "representatives", "study abroad", "erasmus",
        "sponsors", "alumni", "events", "news",
        "tərəfdaşlar", "xəbərlər", "tədbirlər", "məzunlar",
        "ortaklar", "partnerler", "haberler", "etkinlikler", "mezunlar",
        "nachrichten", "veranstaltungen", "auslandsstudium",
        "partenaires", "actualités", "événements",
        "협력", "뉴스", "행사", "동문",
    )
```

- [ ] **Step 2: Run them to verify they fail**

Run: `POSTGRES_DB=tehsil_provenance_gate uv run pytest tests/research/test_vouch.py -q --create-db`
Expected: FAIL with `ModuleNotFoundError: No module named 'apps.research.vouch'`.

- [ ] **Step 3: Implement**

Create `apps/research/vouch.py`:

```python
"""Vouching by link: deterministic, one hop, part-of only (spec §5.3).

A body no authority names -- a constituent institute, a joint-venture campus --
is RECOGNISED(vouched_by_link) when a RECOGNISED body's own main host links to
it from a structural position. The candidate's link only says where to look;
the recogniser's reverse link is the evidence. No model call, and a body
admitted this way vouches for nothing.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

import lxml.etree
import lxml.html

from .fetch import fetch_page
from .fetch.types import FetchedPage
from .hosts import registrable_domain
from .provenance import Reason
from .recognition import usable

#: Headings and link texts that mean "part of us", in the five languages the
#: spec names plus English. Pinned by tests/research/test_vouch.py.
STRUCTURAL_TERMS: tuple[str, ...] = (
    "faculties", "faculty", "schools", "institutes", "campuses", "branches",
    "affiliated institutions",
    "fakültələr", "fakültə", "institutlar", "filiallar", "kampuslar",
    "fakülteler", "enstitüler", "yüksekokullar", "kampüsler",
    "fakultäten", "fachbereiche", "institute", "standorte",
    "facultés", "écoles", "instituts", "composantes",
    "단과대학", "대학원", "캠퍼스", "부속기관",
)
#: Pages universities use to link bodies that are NOT part of them: agents,
#: exchange partners, sponsors. A heading here never vouches.
EXCLUDED_TERMS: tuple[str, ...] = (
    "partners", "partner", "agents", "representatives", "study abroad", "erasmus",
    "sponsors", "alumni", "events", "news",
    "tərəfdaşlar", "xəbərlər", "tədbirlər", "məzunlar",
    "ortaklar", "partnerler", "haberler", "etkinlikler", "mezunlar",
    "nachrichten", "veranstaltungen", "auslandsstudium",
    "partenaires", "actualités", "événements",
    "협력", "뉴스", "행사", "동문",
)
MAX_STRUCTURAL_PAGES = 10
_MAX_RECOGNISERS = 3
_STRUCTURAL_XPATH = "//nav//a[@href] | //header//a[@href] | //footer//a[@href] | //*[@role='navigation']//a[@href]"


@dataclass(frozen=True)
class VouchResult:
    vouch_url: str = ""
    recogniser_domain: str = ""
    failed: bool = False


def _matches(text: str, terms: tuple[str, ...]) -> bool:
    lowered = text.casefold()
    return any(re.search(rf"(?<!\w){re.escape(term)}(?!\w)", lowered) for term in terms)


def _is_structural(text: str) -> bool:
    return _matches(text, STRUCTURAL_TERMS) and not _matches(text, EXCLUDED_TERMS)


def _document(page: FetchedPage) -> lxml.html.HtmlElement | None:
    try:
        return lxml.html.fromstring(page.body)
    except (lxml.etree.ParserError, ValueError):
        return None


def _links(page: FetchedPage, xpath: str = "//a[@href]") -> list[tuple[str, str]]:
    document = _document(page)
    if document is None:
        return []
    return [
        (urljoin(page.final_url, str(a.get("href"))), " ".join(a.text_content().split()))
        for a in document.xpath(xpath)
    ]


def _heading(page: FetchedPage) -> str:
    document = _document(page)
    if document is None:
        return ""
    h1 = document.xpath("//h1")
    text = h1[0].text_content() if h1 else " ".join(document.xpath("//title/text()"))
    return " ".join(text.split())


def _main_host(url: str, domain: str) -> bool:
    return (urlsplit(url).hostname or "") in (domain, f"www.{domain}")


def find_vouch(
    candidate: str,
    recognisers: Mapping[str, str],
    *,
    fetch: Callable[..., FetchedPage] | None = None,
) -> VouchResult:
    fetch = fetch or fetch_page
    home = fetch(f"https://{candidate}/", purpose="provenance")
    if not usable(home):
        return VouchResult(failed=True)
    pointers = list(
        dict.fromkeys(
            domain
            for domain in (registrable_domain(url) for url, _text in _links(home))
            if domain and domain != candidate
            and recognisers.get(domain) not in (None, Reason.VOUCHED_BY_LINK)
        )
    )[:_MAX_RECOGNISERS]
    budget = [MAX_STRUCTURAL_PAGES]
    failed = False
    for recogniser in pointers:
        url, broke = _reverse_link(recogniser, candidate, fetch, budget)
        failed |= broke
        if url:
            return VouchResult(vouch_url=url, recogniser_domain=recogniser)
    return VouchResult(failed=failed)


def _reverse_link(
    recogniser: str, candidate: str, fetch: Callable[..., FetchedPage], budget: list[int]
) -> tuple[str, bool]:
    home = fetch(f"https://{recogniser}/", purpose="provenance")
    if not usable(home):
        return "", True
    if not _main_host(home.final_url, recogniser):
        return "", False
    if any(registrable_domain(url) == candidate for url, _text in _links(home, _STRUCTURAL_XPATH)):
        return home.final_url, False
    frontier = [url for url, text in _links(home) if _main_host(url, recogniser) and _is_structural(text)]
    seen = {home.final_url}
    for depth in (1, 2):
        following: list[str] = []
        for url in dict.fromkeys(frontier):
            if url in seen or budget[0] <= 0:
                continue
            seen.add(url)
            budget[0] -= 1
            fetched = fetch(url, purpose="provenance")
            if not usable(fetched) or not _main_host(fetched.final_url, recogniser):
                continue
            if not _is_structural(_heading(fetched)):
                continue
            if any(registrable_domain(link) == candidate for link, _text in _links(fetched)):
                return fetched.final_url, False
            if depth == 1:
                following += [
                    link for link, text in _links(fetched)
                    if _main_host(link, recogniser) and _is_structural(text)
                ]
        frontier = following
    return "", False
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `POSTGRES_DB=tehsil_provenance_gate uv run pytest tests/research/test_vouch.py -q`
Expected: PASS.

- [ ] **Step 5: Run the four checks.**

- [ ] **Step 6: Commit**

```bash
git -C /home/orkhan/Desktop/provenance-gate add apps/research/vouch.py tests/research/test_vouch.py
git -C /home/orkhan/Desktop/provenance-gate commit -m "feat(research): one-hop structural vouching by the recogniser's own link"
```

---

### Task 11: RDAP, the domain-takeover signal

**Files:**
- Create: `apps/research/rdap.py`
- Test: `tests/research/test_rdap.py`

**Interfaces:**
- Consumes: `egress.fetch_data_file`, `egress.SourceBlocked`, `egress.UnsafeTarget`, `provenance.RdapResult`.
- Produces (all in `apps.research.rdap`):
  - `BOOTSTRAP_URL`
  - `NO_REGISTRATION_DATE: tuple[str, ...]`
  - `load_bootstrap(*, fetch=None) -> dict[str, str]`
  - `registration_date(domain: str, bootstrap: Mapping[str, str], *, fetch=None) -> RdapResult`

- [ ] **Step 1: Write the failing tests**

Create `tests/research/test_rdap.py`:

```python
"""RDAP through IANA's bootstrap, straight to the registry (spec §5.5). It
never blocks, and a registry that gives no date is skipped, never passed."""

from datetime import date

from apps.research.egress import FetchResult, SourceBlocked
from apps.research.rdap import BOOTSTRAP_URL, load_bootstrap, registration_date

#: Subset of data.iana.org/rdap/dns.json (publication 2026-09-16).
BOOTSTRAP = (
    b'{"version": "1.0", "services": ['
    b'[["berlin"], ["https://rdap.nic.berlin/v1/"]],'
    b'[["com", "net"], ["https://rdap.verisign.com/com/v1/"]],'
    b'[["kr", "xn--3e0b707e"], ["https://rdap.nic.or.kr/"]],'
    b'[["uk"], ["https://rdap.nominet.uk/uk/"]],'
    b'[["de"], ["http://rdap.denic.de/", "https://rdap.denic.de/"]]]}'
)
#: rdap.nic.berlin/v1/domain/esmt.berlin, 2026-09-26 (events only).
ESMT = (
    b'{"ldhName": "esmt.berlin", "events": ['
    b'{"eventAction": "registration", "eventDate": "2016-06-06T16:12:51.077302Z"},'
    b'{"eventAction": "last changed", "eventDate": "2024-02-23T12:46:51.339528Z"}]}'
)
#: DENIC answers with a last-changed date only.
DENIC = b'{"ldhName": "tum.de", "events": [{"eventAction": "last changed", "eventDate": "2025-01-01T00:00:00Z"}]}'


class Files:
    def __init__(self, bodies: dict[str, bytes]) -> None:
        self.bodies, self.calls = bodies, []

    def __call__(self, url: str, **kwargs: object) -> FetchResult:
        self.calls.append((url, kwargs))
        if url not in self.bodies:
            raise SourceBlocked("source returned HTTP 404")
        return FetchResult(url, (), "application/rdap+json", self.bodies[url])


def test_the_bootstrap_maps_each_tld_to_its_https_registry() -> None:
    table = load_bootstrap(fetch=Files({BOOTSTRAP_URL: BOOTSTRAP}))
    assert table["berlin"] == "https://rdap.nic.berlin/v1/"
    assert table["de"] == "https://rdap.denic.de/"
    assert table["xn--3e0b707e"] == "https://rdap.nic.or.kr/"


def test_a_registration_date_is_read_from_the_registry_itself() -> None:
    table = load_bootstrap(fetch=Files({BOOTSTRAP_URL: BOOTSTRAP}))
    files = Files({"https://rdap.nic.berlin/v1/domain/esmt.berlin": ESMT})
    result = registration_date("esmt.berlin", table, fetch=files)
    assert (result.status, result.registered) == ("ok", date(2016, 6, 6))
    assert files.calls[0][1] == {"require_https": True}


def test_a_registry_with_no_registration_date_is_skipped_not_passed() -> None:
    table = load_bootstrap(fetch=Files({BOOTSTRAP_URL: BOOTSTRAP}))
    result = registration_date("tum.de", table, fetch=Files({"https://rdap.denic.de/domain/tum.de": DENIC}))
    assert (result.status, result.registered) == ("skipped", None)


def test_ac_uk_is_skipped_without_asking_nominet() -> None:
    files = Files({})
    result = registration_date("ox.ac.uk", {"uk": "https://rdap.nominet.uk/uk/"}, fetch=files)
    assert result.status == "skipped" and files.calls == []


def test_a_tld_with_no_rdap_service_is_skipped() -> None:
    assert registration_date("asoiu.edu.az", {}, fetch=Files({})).status == "skipped"


def test_a_registry_failure_is_failed_never_passed() -> None:
    result = registration_date("esmt.berlin", {"berlin": "https://rdap.nic.berlin/v1/"}, fetch=Files({}))
    assert result.status == "failed" and "404" in result.detail
```

- [ ] **Step 2: Run them to verify they fail**

Run: `POSTGRES_DB=tehsil_provenance_gate uv run pytest tests/research/test_rdap.py -q --create-db`
Expected: FAIL with `ModuleNotFoundError: No module named 'apps.research.rdap'`.

- [ ] **Step 3: Implement**

Create `apps/research/rdap.py`:

```python
"""RDAP registration dates for the domain-takeover signal (spec §5.5).

IANA's bootstrap names each TLD's registry; the registry is called directly,
because rdap.org redirects. Port-43 WHOIS and the .az web form are not used:
they would be new outbound paths with no SSRF guard. Measured 2026-09-26:
.com, .gov, .kr (ac.kr included), .uk under Nominet and .fr give a date; .az,
.de, .tr and ac.uk do not, and those are recorded as skipped, never passed.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from datetime import datetime

from .egress import FetchResult, SourceBlocked, UnsafeTarget, fetch_data_file
from .provenance import RdapResult

BOOTSTRAP_URL = "https://data.iana.org/rdap/dns.json"
#: Registered by Jisc, which does not answer Nominet's RDAP.
NO_REGISTRATION_DATE: tuple[str, ...] = ("ac.uk",)

FetchFile = Callable[..., FetchResult]


def load_bootstrap(*, fetch: FetchFile | None = None) -> dict[str, str]:
    body = json.loads((fetch or fetch_data_file)(BOOTSTRAP_URL, require_https=True).body)
    table: dict[str, str] = {}
    for tlds, urls in body.get("services", []):
        https = [str(url) for url in urls if str(url).startswith("https://")]
        if https:
            for tld in tlds:
                table[str(tld).casefold()] = https[0]
    return table


def registration_date(
    domain: str, bootstrap: Mapping[str, str], *, fetch: FetchFile | None = None
) -> RdapResult:
    if any(domain == suffix or domain.endswith(f".{suffix}") for suffix in NO_REGISTRATION_DATE):
        return RdapResult("skipped", detail="ac.uk is registered by Jisc, which does not answer RDAP")
    tld = domain.rsplit(".", 1)[-1]
    base = bootstrap.get(tld)
    if base is None:
        return RdapResult("skipped", detail=f"no RDAP service for .{tld} in IANA's bootstrap")
    try:
        answer = json.loads(
            (fetch or fetch_data_file)(f"{base.rstrip('/')}/domain/{domain}", require_https=True).body
        )
    except (SourceBlocked, UnsafeTarget, ValueError) as error:
        return RdapResult("failed", detail=str(error)[:200])
    events = answer.get("events", []) if isinstance(answer, dict) else []
    for event in events:
        if isinstance(event, dict) and event.get("eventAction") == "registration":
            try:
                return RdapResult("ok", registered=datetime.fromisoformat(str(event["eventDate"])).date())
            except (KeyError, ValueError):
                break
    return RdapResult("skipped", detail="the registry reports no registration date")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `POSTGRES_DB=tehsil_provenance_gate uv run pytest tests/research/test_rdap.py -q`
Expected: PASS.

- [ ] **Step 5: Run the four checks.**

- [ ] **Step 6: Commit**

```bash
git -C /home/orkhan/Desktop/provenance-gate add apps/research/rdap.py tests/research/test_rdap.py
git -C /home/orkhan/Desktop/provenance-gate commit -m "feat(research): RDAP registration dates through IANA's bootstrap"
```

---

### Task 12: The `provenance_check` job

**Files:**
- Create: `apps/research/provenance_job.py`, `apps/research/management/commands/provenance_check.py`
- Modify: `tests/research/provenance_helpers.py` (adds `attach_evidence`, `attach_snapshot`, `recognise`)
- Test: `tests/research/test_provenance_check.py`

**Interfaces:**
- Consumes: everything from Tasks 2–11.
- Produces (all in `apps.research.provenance_job`):
  - `NAMED_TAG = "NAMED_PROGRAM"`
  - `Deps` (a dataclass). Its fields: `fetch`, `fetch_file`, `ror_call`, `jev_post`, `load`, `store`, `sources`, `mill_rows`, `bootstrap`, `bootstrap_failed`, `run_id`. Its methods: `object_store()` and `rdap(domain) -> RdapResult`.
  - `next_check(decision: Decision, now: datetime) -> datetime | None`
  - `check_body(organisation: Organisation, *, now: datetime, deps: Deps) -> ProvenanceVerdict`
  - `bodies_in_play() -> QuerySet[Organisation]`
  - `due(now: datetime) -> QuerySet[Organisation]`
  - `run_checks(bodies: QuerySet[Organisation], *, now: datetime, deps: Deps) -> Counter[str]`
  - The `manage.py provenance_check [--all] [--domain D]...` command
- Test helpers (in `tests/research/provenance_helpers.py`):
  - `attach_evidence(program, *urls) -> list[OfficialEvidenceClaim]`
  - `attach_snapshot(claim, text: str, store: FakeStore) -> None`
  - `recognise(organisation, bound_domain, reason="register", *, now=None) -> ProvenanceVerdict`

The spec leaves the scope open; this plan decides it (see "Decisions" above): only bodies in play are checked. The job runs outside any tenant transaction, one body at a time, and holds no transaction across HTTP.

- [ ] **Step 1: Extend the helpers**

In `tests/research/provenance_helpers.py`, factor `evidence_program`'s claim-writing loop into `attach_evidence` and add two more builders. The imports shown go at the top of the file (ruff E402):

```python
from apps.funding.models import OfficialSourceSnapshot
from apps.research.models import ProvenanceVerdict
from apps.research.provenance import record_verdict, verdict_of


def attach_evidence(program: Program, *urls: str) -> list[OfficialEvidenceClaim]:
    claims = []
    for url in urls:
        source, _ = OfficialSource.objects.get_or_create(
            canonical_url=url,
            defaults={"publisher": urlsplit(url).hostname or url, "source_type": "PROGRAM"},
        )
        claim = OfficialEvidenceClaim.objects.create(
            source=source, claim=f"{program.name} is offered", evidence_strength="DIRECT",
            visibility="STUDENT_FACING", claim_class="IDENTITY", last_checked_at=timezone.now(),
        )
        ProgramEvidenceClaim.objects.create(program=program, evidence_claim=claim)
        claims.append(claim)
    all_urls = OfficialEvidenceClaim.objects.filter(program=program).values_list(
        "source__canonical_url", flat=True
    )
    domain, institutional = evidence_of(all_urls)
    Program.objects.filter(id=program.id).update(
        evidence_domain=domain, evidence_institutional=institutional
    )
    program.refresh_from_db()
    return claims


def attach_snapshot(claim: OfficialEvidenceClaim, text: str, store: FakeStore) -> None:
    key = f"official-sources/{uuid4()}"
    snapshot = OfficialSourceSnapshot.objects.create(
        source=claim.source, s3_key=key, s3_version_id="1", sha256=uuid4().hex * 2,
        final_url=claim.source.canonical_url, redirect_chain=[], retrieved_at=timezone.now(),
        admissions_cycle="2027", content_type="text/html", byte_size=len(text),
    )
    OfficialEvidenceClaim.objects.filter(id=claim.id).update(snapshot=snapshot)
    store.objects[key] = f"<p>{text}</p>".encode()


def recognise(
    organisation: Organisation, bound_domain: str, reason: str = "register", *, now=None
) -> ProvenanceVerdict:
    return record_verdict(
        organisation, verdict=verdict_of(reason), reason_code=reason, bound_domain=bound_domain,
        evidence={}, now=now or timezone.now(), next_check_at=None,
    )
```

Replace `evidence_program` with this version. The signature is the same plus `joint`, and it now builds on `attach_evidence`:

```python
def evidence_program(
    *urls: str,
    name: str = "MSc Computer Science",
    institution: Institution | None = None,
    joint: bool = False,
) -> Program:
    """A programme whose OfficialEvidenceClaims sit on `urls`, with its evidence
    columns set the way the catalogue writer sets them. `joint` makes a JOINT
    programme, which carries no Institution (Program's provision-type check)."""
    if joint:
        institution = None
    else:
        institution = institution or Institution.objects.create(
            canonical_key=f"institution:{uuid4()}", name="Example University",
            country_code="DE", official_website="https://university.example.test/",
        )
    program = Program.objects.create(
        institution=institution, canonical_key=f"program:{uuid4()}", name=name,
        campus_name="Main", city="Munich", country_code="DE", location_key=f"de:{uuid4()}",
        degree_level="MASTER", teaching_languages=["English"], duration_months=24,
        provision_type="JOINT" if joint else "SINGLE", provider_text="A; B" if joint else "",
    )
    attach_evidence(program, *urls)
    return program
```

- [ ] **Step 2: Write the failing tests**

Create `tests/research/test_provenance_check.py`:

```python
"""provenance_check end to end, with every transport faked (spec §7.1, §11's
known-answer set). The job holds no tenant transaction and calls no model on
the admit path."""

from datetime import UTC, date, datetime, timedelta
from io import StringIO
from uuid import uuid4

import pytest
from django.core.management import call_command
from django.utils import timezone

from apps.funding.models import FundingOpportunity, FundingOpportunityEvidenceClaim
from apps.research.blocking import read_mill_list
from apps.research.closed_lists import ListRow, record_list
from apps.research.egress import FetchResult, SourceBlocked
from apps.research.models import ClosedList, Organisation, ProvenanceVerdict, RegisterEntry
from apps.research.provenance import Decision
from apps.research.provenance_job import (
    Deps,
    bodies_in_play,
    check_body,
    due,
    next_check,
    run_checks,
)
from apps.research.recognition import ProvenanceSource, load_register
from apps.research.services import acquire_domain_lease
from tests.research.provenance_helpers import (
    FakeFetch,
    FakeStore,
    attach_snapshot,
    evidence_program,
    make_body,
    make_list,
    page,
    recognise,
)
from tests.research.test_blocking import DIPLOMA_SALE, FEE_RELEASE
from tests.research.test_provenance_registers import (
    ENIC_DE_URL,
    ENIC_GERMANY,
    HRK,
    HRK_TSV,
    SFC,
    SFC_HTML,
    SFC_URL,
)
from tests.research.test_rdap import ESMT
from tests.research.test_vouch import ASOIU, ASOIU_HOME, UFAZ, UFAZ_HOME

pytestmark = pytest.mark.django_db
NOW = timezone.now()
QUIET = "<html><body><h1>Home</h1></body></html>"


def _ror(**records):
    def call(url, *, params, headers):
        domain = params["query.advanced"].removeprefix("domains:")
        return {"items": [records[domain]] if domain in records else []}
    return call


def _record(domain: str, country: str) -> dict:
    return {"id": f"https://ror.org/{uuid4().hex[:9]}", "domains": [domain], "links": [],
            "locations": [{"geonames_details": {"country_code": country}}]}


class Files:
    def __init__(self, bodies: dict[str, bytes] | None = None) -> None:
        self.bodies = bodies or {}

    def __call__(self, url: str, **_kwargs: object) -> FetchResult:
        if url not in self.bodies:
            raise SourceBlocked("source returned HTTP 404")
        return FetchResult(url, (), "application/rdap+json", self.bodies[url])


def _deps(**overrides) -> Deps:
    fields = dict(
        fetch=FakeFetch({}), fetch_file=Files(), ror_call=_ror(), jev_post=_no_jev,
        store=FakeStore(), sources=(), mill_rows=(), bootstrap={},
    )
    fields.update(overrides)
    return Deps(**fields)


def _no_jev(url, *, payload, headers):
    raise AssertionError("no model call was expected")


def _register(slug: str, country: str, *websites: str, unbound: str = "") -> ProvenanceSource:
    spec = make_list(slug, country_code=country)
    rows = tuple(
        ListRow(external_key=w, name=w, kind="INSTITUTION", website=f"https://{w}", page_url="",
                country_code=country, home_cells=("ANY",), host_cells=(country,),
                rejected_reason="", source_url=spec.source_url, verified_on=date(2026, 9, 26))
        for w in websites
    )
    record_list(spec, rows, now=NOW)
    if unbound:
        RegisterEntry.objects.create(register=slug, external_key=unbound, name=unbound,
                                     resolution="UNRESOLVED", last_seen=NOW)
    ClosedList.objects.filter(slug=slug).update(loaded_at=NOW)
    return ProvenanceSource(slug=slug, role="register", named_by_hand_because="test")


def _verdict(domain: str, deps: Deps, *, country: str = "", kind: str = "INSTITUTION") -> ProvenanceVerdict:
    body = Organisation.objects.filter(domains__registrable_domain=domain).first() or make_body(
        domain, kind=kind, country_code=country
    )
    return check_body(body, now=NOW, deps=deps)


def test_tum_is_recognised_after_loading_germanys_register(settings) -> None:
    settings.JEV_API_KEY = ""
    make_list("de_hochschulkompass", country_code="DE",
              source_url="https://www.hochschulkompass.de/hochschulen/downloads.html")
    deps = _deps(
        ror_call=_ror(**{"tum.de": _record("tum.de", "DE")}),
        fetch=FakeFetch({ENIC_DE_URL: page(ENIC_DE_URL, ENIC_GERMANY)}),
        fetch_file=Files({HRK.data_url: HRK_TSV}), sources=(HRK,), load=load_register,
    )
    verdict = _verdict("tum.de", deps)
    assert (verdict.verdict, verdict.reason_code, verdict.bound_domain) == (
        "RECOGNISED", "register", "tum.de",
    )
    assert verdict.evidence["content_checks"] == "skipped"
    assert verdict.next_check_at == NOW + timedelta(days=30)


def test_edinburgh_is_recognised_via_the_sfc_list() -> None:
    make_list("gb_sfc_universities", country_code="GB", source_url=SFC_URL)
    deps = _deps(
        ror_call=_ror(**{"ed.ac.uk": _record("ed.ac.uk", "GB")}),
        fetch=FakeFetch({SFC_URL: page(SFC_URL, SFC_HTML)}), sources=(SFC,), load=load_register,
    )
    assert _verdict("ed.ac.uk", deps).reason_code == "register"


def test_ufaz_is_recognised_by_asoius_structural_link() -> None:
    recognise(make_body("asoiu.edu.az", country_code="AZ"), "asoiu.edu.az", "curated_list")
    deps = _deps(fetch=FakeFetch({UFAZ: page(UFAZ, UFAZ_HOME), ASOIU: page(ASOIU, ASOIU_HOME)}))
    verdict = _verdict("ufaz.az", deps)
    assert (verdict.reason_code, verdict.evidence["admitted_via"]) == (
        "vouched_by_link", "asoiu.edu.az",
    )


def test_nyenrode_is_unbound_while_its_register_row_has_no_website() -> None:
    source = _register("nl_register", "NL", "uva.nl", unbound="Nyenrode Business Universiteit")
    deps = _deps(sources=(source,),
                 fetch=FakeFetch({"https://nyenrode.nl/": page("https://nyenrode.nl/", QUIET)}))
    assert _verdict("nyenrode.nl", deps, country="NL").reason_code == "no_domain_binding"


def test_a_free_zone_branch_missing_from_the_federal_register_is_absent_not_blocked() -> None:
    source = _register("ae_register", "AE", "uaeu.ac.ae")
    url = "https://branch-campus-dubai.ae/"
    verdict = _verdict("branch-campus-dubai.ae",
                       _deps(sources=(source,), fetch=FakeFetch({url: page(url, QUIET)})),
                       country="AE")
    assert (verdict.verdict, verdict.reason_code) == ("UNCONFIRMED", "absent_from_register")


def test_a_rebranded_or_taken_over_domain_is_unconfirmed() -> None:
    source = _register("de_register", "DE", "esmt.berlin")
    body = Organisation.objects.get(domains__registrable_domain="esmt.berlin")
    recognise(body, "esmt.berlin", now=datetime(2015, 1, 1, tzinfo=UTC))
    deps = _deps(sources=(source,), bootstrap={"berlin": "https://rdap.nic.berlin/v1/"},
                 fetch_file=Files({"https://rdap.nic.berlin/v1/domain/esmt.berlin": ESMT}))
    verdict = check_body(body, now=NOW, deps=deps)
    assert verdict.reason_code == "domain_registered_after_listing"
    assert verdict.evidence["rdap"]["date"] == "2016-06-06"


@pytest.mark.parametrize(
    "domain",
    ["bircham.edu", "aiu.edu", "warnborough.ac.uk", "iiu-edu.eu", "breyerstate.com", "awuedu.org"],
)
def test_a_mill_is_blocked_by_its_domain(domain: str) -> None:
    verdict = _verdict(domain, _deps(mill_rows=read_mill_list()))
    assert (verdict.verdict, verdict.reason_code, verdict.next_check_at) == (
        "BLOCKED", "mill_list", None,
    )


def test_a_real_business_school_with_vendor_wording_is_a_conflict_not_a_block(settings) -> None:
    settings.JEV_API_KEY = "k"
    source = _register("de_register", "DE", "business-school-fixture.de")
    store = FakeStore()
    program = evidence_program("https://www.business-school-fixture.de/mba")
    attach_snapshot(program.evidence_claims.get(), DIPLOMA_SALE, store)

    def jev(url, *, payload, headers):
        return {"model": "typesafe/jev-1.13.0",
                "answers": {f"s{i}": {"noul": 0.95} for i in range(len(payload["state"]["sentences"]))}}

    verdict = _verdict("business-school-fixture.de",
                       _deps(sources=(source,), store=store, jev_post=jev))
    assert (verdict.verdict, verdict.reason_code) == ("UNCONFIRMED", "veto_conflict")


def test_a_fee_to_release_an_award_blocks_an_unrecognised_funder(settings) -> None:
    settings.JEV_API_KEY = "k"
    body = make_body("grants-fixture-foundation.com", kind="PRIVATE_FOUNDATION")
    award = FundingOpportunity.objects.create(
        canonical_key=f"read:holder:{uuid4()}", name="Grant", family="PRIVATE_FOUNDATION",
        scope_type="HOLDER", organisation=body, served=True,
    )
    claim = evidence_program("https://grants-fixture-foundation.com/grant").evidence_claims.get()
    FundingOpportunityEvidenceClaim.objects.create(opportunity=award, evidence_claim=claim)
    store = FakeStore()
    attach_snapshot(claim, FEE_RELEASE, store)

    def jev(url, *, payload, headers):
        return {"model": "jev-1.13", "answers": {"s0": {"noul": 0.97}}}

    url = "https://grants-fixture-foundation.com/"
    verdict = check_body(body, now=NOW, deps=_deps(store=store, jev_post=jev,
                                                    fetch=FakeFetch({url: page(url, QUIET)})))
    assert (verdict.verdict, verdict.reason_code) == ("BLOCKED", "fee_to_release_award")


def test_a_lookalike_funder_is_unconfirmed() -> None:
    url = "https://daad-scholarships.org/"
    verdict = _verdict("daad-scholarships.org", _deps(fetch=FakeFetch({url: page(url, QUIET)})),
                       kind="PRIVATE_FOUNDATION")
    assert verdict.verdict == "UNCONFIRMED"


def test_a_go_kr_funder_is_recognised_by_its_government_zone() -> None:
    verdict = _verdict("studyinkorea.go.kr", _deps(), kind="NATIONAL_GOVERNMENT")
    assert verdict.reason_code == "government_zone"


def test_an_unverified_reviewed_row_is_unmapped() -> None:
    spec = make_list("az_heis", country_code="AZ")
    record_list(spec, (ListRow(
        external_key="x", name="Azerbaijan Technical University", kind="INSTITUTION",
        website="https://aztu.edu.az", page_url="", country_code="AZ", home_cells=("ANY",),
        host_cells=("AZ",), rejected_reason="", source_url=spec.source_url,
        verified_on=date(2026, 9, 26)),), now=NOW)
    url = "https://aztu.edu.az/"
    deps = _deps(sources=(ProvenanceSource(slug="az_heis", role="curated_list"),),
                 fetch=FakeFetch({url: page(url, QUIET)}))
    assert _verdict("aztu.edu.az", deps).reason_code == "unmapped_list_row"


def test_a_failed_lookup_is_unconfirmed_and_retried_tomorrow() -> None:
    def broken(url, *, params, headers):
        raise SourceBlocked("api returned HTTP 503")

    verdict = _verdict("unknown-college.edu", _deps(ror_call=broken))
    assert (verdict.reason_code, verdict.next_check_at) == ("lookup_failed", NOW + timedelta(days=1))


def test_a_country_register_held_by_another_loader_is_not_loaded_yet() -> None:
    make_list("gb_sfc_universities", country_code="GB", source_url=SFC_URL)
    acquire_domain_lease("register:gb_sfc_universities", interval=timedelta(hours=1))
    url = "https://some-college.ac.uk/"
    verdict = _verdict("some-college.ac.uk",
                       _deps(sources=(SFC,), fetch=FakeFetch({url: page(url, QUIET)})), country="GB")
    assert verdict.reason_code == "register_not_loaded"


def test_outages_never_downgrade_a_recognised_body(settings) -> None:
    settings.JEV_API_KEY = "k"
    source = _register("de_register", "DE", "outage-university.de")
    store = FakeStore()
    program = evidence_program("https://www.outage-university.de/msc")
    attach_snapshot(program.evidence_claims.get(), FEE_RELEASE, store)

    def jev_down(url, *, payload, headers):
        raise SourceBlocked("api returned HTTP 529")

    deps = _deps(sources=(source,), store=store, jev_post=jev_down, bootstrap=None,
                 fetch_file=Files())
    verdict = _verdict("outage-university.de", deps)
    assert (verdict.verdict, verdict.reason_code) == ("RECOGNISED", "register")
    assert verdict.evidence["rdap"]["status"] == "failed"
    assert verdict.evidence["content_checks"] == "skipped"


def test_admission_never_calls_a_model(settings) -> None:
    settings.JEV_API_KEY = "k"
    source = _register("de_register", "DE", "quiet-university.de")
    calls: list[object] = []

    def jev(url, *, payload, headers):
        calls.append(payload)
        return {"model": "jev-1.13", "answers": {}}

    verdict = _verdict("quiet-university.de", _deps(sources=(source,), jev_post=jev))
    assert verdict.verdict == "RECOGNISED" and calls == []


def test_bodies_in_play_and_due() -> None:
    evidence_program("https://www.tum.de/msc")
    tum = make_body("tum.de")
    funder = make_body("stiftung-fixture.de", kind="PRIVATE_FOUNDATION")
    FundingOpportunity.objects.create(canonical_key=f"k:{uuid4()}", name="A", family="PRIVATE_FOUNDATION",
                                      scope_type="HOLDER", organisation=funder)
    idle = make_body("vgm-foundation-fixture.org.tr", kind="PRIVATE_FOUNDATION")
    assert set(bodies_in_play()) == {tum, funder}
    recognise(tum, "tum.de")
    ProvenanceVerdict.objects.filter(organisation=tum).update(next_check_at=NOW + timedelta(days=5))
    assert set(due(NOW)) == {funder}
    assert idle not in set(due(NOW))


@pytest.mark.parametrize(
    ("verdict", "reason", "after"),
    [
        ("RECOGNISED", "register", timedelta(days=30)),
        ("BLOCKED", "mill_list", None),
        ("UNCONFIRMED", "lookup_failed", timedelta(days=1)),
        ("UNCONFIRMED", "register_not_loaded", timedelta(days=1)),
        ("UNCONFIRMED", "absent_from_register", timedelta(days=7)),
    ],
)
def test_next_check(verdict, reason, after) -> None:
    expected = NOW + after if after else None
    assert next_check(Decision(verdict, reason, "x.de", {}), NOW) == expected


def test_one_failing_body_never_stops_the_run() -> None:
    evidence_program("https://www.good-uni-fixture.de/msc")
    evidence_program("https://www.bad-uni-fixture.de/msc")
    make_body("good-uni-fixture.de")
    make_body("bad-uni-fixture.de")

    def ror(url, *, params, headers):
        if "bad-uni" in params["query.advanced"]:
            raise RuntimeError("unexpected")
        return {"items": []}

    tally = run_checks(bodies_in_play(), now=NOW, deps=_deps(ror_call=ror))
    assert tally["error"] == 1 and sum(tally.values()) == 2


def test_the_command_checks_one_domain(monkeypatch) -> None:
    from apps.research.management.commands import provenance_check

    make_body("studyinkorea.go.kr", kind="NATIONAL_GOVERNMENT")
    monkeypatch.setattr(provenance_check, "Deps", lambda: _deps())
    out = StringIO()
    call_command("provenance_check", "--domain", "studyinkorea.go.kr", stdout=out)
    assert "government_zone: 1" in out.getvalue()
```

- [ ] **Step 3: Run them to verify they fail**

Run: `POSTGRES_DB=tehsil_provenance_gate uv run pytest tests/research/test_provenance_check.py -q --create-db`
Expected: FAIL with `ModuleNotFoundError: No module named 'apps.research.provenance_job'`.

- [ ] **Step 4: Implement**

Create `apps/research/provenance_job.py`:

```python
"""provenance_check: gather evidence, decide, record (institution provenance
gate spec §7.1).

Its own worker job, outside any tenant transaction, one body at a time: a
register load is minutes of HTTP and must never sit inside the transaction
`handle_research_message` holds (CLAUDE.md records the same cost for
`read_and_derive`). Pack building only READS what this writes. Only bodies in
play are checked -- programme evidence domains, HOLDER-award holders and bodies
recorded for a named programme -- because vouching can cost ~11 vendor fetches
a body and the register holds thousands of bodies no student is shown.
"""

from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from django.conf import settings
from django.db.models import Q, QuerySet

from apps.funding.models import Program

from .blocking import MillRow, body_page_texts, content_facts, mill_hit, read_mill_list
from .egress import FetchResult, SourceBlocked, fetch_data_file, fetch_json_api
from .fetch import fetch_page
from .fetch.types import FetchedPage
from .hosts import is_hosting_platform
from .models import Organisation, ProvenanceVerdict
from .provenance import (
    Decision,
    Facts,
    RdapResult,
    Reason,
    Recognition,
    Verdict,
    decide,
    record_verdict,
)
from .rdap import load_bootstrap, registration_date
from .recognition import (
    ProvenanceSource,
    ensure_country_loaded,
    government_zone,
    list_recognitions,
    load_register,
    read_sources,
    register_state,
    ror_recognitions,
)
from .ror import ror_facts
from .storage import S3ObjectStore
from .vouch import find_vouch

logger = logging.getLogger(__name__)

NAMED_TAG = "NAMED_PROGRAM"
_SOON = timedelta(days=1)
_UNCONFIRMED_RETRY = timedelta(days=7)
_RETRY_SOON = frozenset({Reason.LOOKUP_FAILED, Reason.REGISTER_NOT_LOADED, Reason.NOT_EVALUATED})


@dataclass
class Deps:
    """Every outbound path, injectable. One per run: `run_id` keys the Jev limit."""

    fetch: Callable[..., FetchedPage] = fetch_page
    fetch_file: Callable[..., FetchResult] = fetch_data_file
    ror_call: Callable[..., dict[str, object]] = fetch_json_api
    jev_post: Callable[..., dict[str, object]] = fetch_json_api
    load: Callable[..., object] = load_register
    store: Any = None
    sources: tuple[ProvenanceSource, ...] | None = None
    mill_rows: tuple[MillRow, ...] | None = None
    bootstrap: dict[str, str] | None = None
    bootstrap_failed: bool = False
    run_id: UUID = field(default_factory=uuid4)

    def object_store(self) -> Any:
        if self.store is None:
            self.store = S3ObjectStore()
        return self.store

    def rdap(self, domain: str) -> RdapResult:
        if self.bootstrap is None and not self.bootstrap_failed:
            try:
                self.bootstrap = load_bootstrap(fetch=self.fetch_file)
            except (SourceBlocked, ValueError) as error:
                logger.warning("IANA's RDAP bootstrap unreachable: %s", error)
                self.bootstrap_failed = True
        if self.bootstrap is None:
            return RdapResult("failed", detail="IANA's RDAP bootstrap was unreachable")
        return registration_date(domain, self.bootstrap, fetch=self.fetch_file)


def next_check(decision: Decision, now: datetime) -> datetime | None:
    if decision.verdict == Verdict.BLOCKED:
        return None
    if decision.verdict == Verdict.RECOGNISED:
        return now + timedelta(days=settings.PROVENANCE_CYCLE_DAYS)
    return now + (_SOON if decision.reason_code in _RETRY_SOON else _UNCONFIRMED_RETRY)


def check_body(organisation: Organisation, *, now: datetime, deps: Deps) -> ProvenanceVerdict:
    domain = organisation.primary_domain
    sources = deps.sources if deps.sources is not None else read_sources()
    previous = ProvenanceVerdict.objects.filter(organisation=organisation).first()
    ror = ror_facts(domain, call=deps.ror_call)
    lookup_failed = ror.lookup_failed
    # Operating country from evidence only -- a list's row or ROR -- never
    # from the page (spec §5.2).
    country = organisation.country_code or ror.country_code

    def recognitions() -> tuple[tuple[Recognition, ...], bool]:
        found, unverified = list_recognitions(organisation, sources)
        zone = government_zone(domain)
        return (*found, *ror_recognitions(ror, domain, sources), *((zone,) if zone else ())), unverified

    found, unverified = recognitions()
    state = "not_loaded"
    if not found:
        loaded = ensure_country_loaded(
            country, now=now, cycle=timedelta(days=settings.PROVENANCE_CYCLE_DAYS),
            sources=sources, load=deps.load, fetch=deps.fetch, fetch_file=deps.fetch_file,
            store=deps.object_store(),
        )
        lookup_failed |= loaded == "failed"
        if loaded in ("ok", "none"):
            found, unverified = recognitions()
            state = register_state(country, sources)
    if not found and not is_hosting_platform(domain):
        recognisers = dict(
            ProvenanceVerdict.objects.filter(verdict=Verdict.RECOGNISED)
            .exclude(organisation=organisation)
            .values_list("bound_domain", "reason_code")
        )
        vouch = find_vouch(domain, recognisers, fetch=deps.fetch)
        lookup_failed |= vouch.failed
        if vouch.vouch_url:
            found = (
                Recognition(
                    reason=Reason.VOUCHED_BY_LINK, bound_domain=domain,
                    vouch_url=vouch.vouch_url, admitted_via=vouch.recogniser_domain,
                ),
            )
    register_countries = {r.country_code for r in found if r.reason == Reason.REGISTER and r.country_code}
    mill = mill_hit(
        domain,
        rows=deps.mill_rows if deps.mill_rows is not None else read_mill_list(),
        register_countries=register_countries,
    )
    hits, content_status = content_facts(
        body_page_texts(organisation, domain, store=deps.object_store()),
        run_id=deps.run_id, post=deps.jev_post,
    )
    rdap = deps.rdap(domain) if found else RdapResult("skipped", detail="not recognised")
    decision = decide(
        Facts(
            domain=domain, recognitions=found, unverified_list_row=unverified, mill=mill,
            content_hits=hits, content_checks=content_status, rdap=rdap,
            first_bound_at=previous.first_bound_at if previous else None,
            register_state=state, lookup_failed=lookup_failed,
            was_vouched=previous is not None and previous.reason_code == Reason.VOUCHED_BY_LINK,
        )
    )
    return record_verdict(
        organisation, verdict=decision.verdict, reason_code=decision.reason_code,
        bound_domain=decision.bound_domain, evidence=decision.evidence, now=now,
        next_check_at=next_check(decision, now),
    )


def bodies_in_play() -> QuerySet[Organisation]:
    evidence_domains = Program.objects.exclude(evidence_domain="").values("evidence_domain")
    return (
        Organisation.objects.filter(
            Q(domains__registrable_domain__in=evidence_domains)
            | Q(fundingopportunity__scope_type="HOLDER")
            | Q(found_via__contains=[NAMED_TAG])
        )
        .exclude(status=Organisation.Status.REJECTED)
        .distinct()
    )


def due(now: datetime) -> QuerySet[Organisation]:
    return bodies_in_play().filter(
        Q(provenance__isnull=True) | Q(provenance__next_check_at__lte=now)
    )


def run_checks(bodies: QuerySet[Organisation], *, now: datetime, deps: Deps) -> Counter[str]:
    tally: Counter[str] = Counter()
    for organisation in bodies.order_by("primary_domain"):
        try:
            tally[check_body(organisation, now=now, deps=deps).reason_code] += 1
        except Exception:  # noqa: BLE001 - one body never stops the batch; logged by name
            logger.exception("provenance check failed for %s", organisation.primary_domain)
            tally["error"] += 1
    return tally
```

Create `apps/research/management/commands/provenance_check.py`:

```python
"""Compute provenance verdicts (spec §7.1, §7.7). Outside any tenant transaction.

Default: the bodies in play whose check is due. `--all`: every body in play,
due or not -- the rollout backfill that must run before PROVENANCE_GATE_ENFORCED
is turned on. `--domain`: named bodies only.
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.research.fetch import CATALOG_ROLE_NOTE
from apps.research.models import Organisation
from apps.research.provenance_job import Deps, bodies_in_play, due, run_checks


class Command(BaseCommand):
    help = "Compute provenance verdicts for bodies in play (spec §7.1)." + CATALOG_ROLE_NOTE

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--all", action="store_true", help="every body in play (backfill)")
        parser.add_argument("--domain", action="append", default=[], dest="domains")

    def handle(self, *args: Any, **options: Any) -> None:
        now = timezone.now()
        if options["domains"]:
            bodies = Organisation.objects.filter(
                domains__registrable_domain__in=options["domains"]
            ).distinct()
        elif options["all"]:
            bodies = bodies_in_play()
        else:
            bodies = due(now)
        tally = run_checks(bodies, now=now, deps=Deps())
        for code, count in sorted(tally.items()):
            self.stdout.write(f"{code}: {count}")
        self.stdout.write(f"checked {sum(tally.values())} bodies")
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `POSTGRES_DB=tehsil_provenance_gate uv run pytest tests/research/test_provenance_check.py -q`
Expected: PASS.

- [ ] **Step 6: Add the live checks spec §11 names**

These run by hand with `-m live`, never in CI, and each asserts one real source's shape. TKTA's endpoints belong to Plan 2. The Jev live check is in Task 8.

Create `tests/research/test_provenance_live.py`:

```python
"""Live checks (spec §11): run by hand with `-m live`, never in CI. Each reads
one real source and asserts its shape, so a publisher's change is caught here
before a register load reads nothing."""

import os

import pytest

from apps.research.egress import fetch_data_file
from apps.research.rdap import load_bootstrap, registration_date
from apps.research.recognition import enic_register_links, parse_register, read_sources

pytestmark = pytest.mark.live


def test_live_the_korean_register_parses_and_lists_kentech() -> None:
    korea = next(source for source in read_sources() if source.slug == "kr_univ_info")
    body = fetch_data_file(korea.data_url, max_bytes=korea.max_bytes, require_https=True).body
    rows = parse_register(body, korea)
    assert len(rows) > 1500
    assert any("kentech.ac.kr" in row.website for row in rows)


def test_live_rdap_gives_esmt_berlins_registration_date() -> None:
    result = registration_date("esmt.berlin", load_bootstrap())
    assert result.status == "ok" and result.registered is not None
    assert result.registered.isoformat() == "2016-06-06"


@pytest.mark.django_db
@pytest.mark.skipif(not os.getenv("FIRECRAWL_API_KEY"), reason="FIRECRAWL_API_KEY not set")
def test_live_enic_naric_still_links_the_ofs_register() -> None:
    from apps.research.fetch import fetch_page

    fetched = fetch_page("https://www.enic-naric.net/page-United-Kingdom", purpose="provenance")
    assert any("officeforstudents.org.uk" in link for link in enic_register_links(fetched.body))
```

Run: `POSTGRES_DB=tehsil_provenance_gate uv run pytest tests/research/test_provenance_live.py -q`
Expected: `3 deselected`. These tests only run with `-m live`.

- [ ] **Step 7: Run the four checks.**

- [ ] **Step 8: Commit**

```bash
git -C /home/orkhan/Desktop/provenance-gate add apps/research/provenance_job.py apps/research/management/commands/provenance_check.py tests/research/provenance_helpers.py tests/research/test_provenance_check.py tests/research/test_provenance_live.py
git -C /home/orkhan/Desktop/provenance-gate commit -m "feat(research): provenance_check computes verdicts for bodies in play"
```

---

### Task 13: The gate in `candidate_pool`, tenant copies, and "still being checked"

**Files:**
- Modify:
  - `apps/funding/pool.py`
  - `apps/research/spine.py`
  - `apps/research/services.py:131-240`
  - `apps/research/provenance.py`
  - `apps/funding/views.py:84-103`
- Test: `tests/funding/test_pool_gate.py`

**Interfaces:**
- Consumes: `ProvenanceVerdict`, `OrganisationDomain`, `WAITING_REASONS`, `Verdict`, `Reason`, `settings.PROVENANCE_GATE_ENFORCED`.
- Produces:
  - `PoolResult.pending_bodies: tuple[UUID, ...] = ()`
  - `SpineResult.pending_bodies: tuple[UUID, ...] = ()`
  - `apps.research.provenance.provenance_of_program(program: Program) -> tuple[UUID | None, str]`
  - `apps.research.provenance.provenance_of_award(award: FundingOpportunity) -> tuple[UUID | None, str]`
  - `handle_research_message` writes `provenance_reason_code`/`provenance_body_id` on every candidate and `RecommendationRun.pending_bodies`
  - `_pack_context` adds `"pending_count": int`

- [ ] **Step 1: Write the failing tests**

Create `tests/funding/test_pool_gate.py`:

```python
"""The gate at the pool (spec §3, §7.1-§7.2): only programmes on a RECOGNISED
body's bound domain and HOLDER awards of a RECOGNISED funder, filtered in the
query before the limit, behind PROVENANCE_GATE_ENFORCED."""

from uuid import uuid4

import pytest

from apps.funding.models import FundingOpportunity, Program, RecommendationCandidate
from apps.funding.pool import candidate_pool
from apps.funding.views import _pack_context
from apps.research.provenance import provenance_of_award, provenance_of_program
from apps.research.services import handle_research_message
from apps.tenancy.context import tenant_scope
from tests.conftest import reads_no_catalogue
from tests.funding.conftest import EUR_RATES, make_db_candidate, make_published_pack, make_run
from tests.funding.test_spine import _catalogue, _message
from tests.funding.test_spine import _run as _full_run
from tests.research.provenance_helpers import attach_evidence, evidence_program, make_body, recognise

pytestmark = pytest.mark.django_db


@pytest.fixture
def gate(settings):
    settings.PROVENANCE_GATE_ENFORCED = True


def _award(body, *, name: str = "Foundation Stipend") -> FundingOpportunity:
    return FundingOpportunity.objects.create(
        canonical_key=f"read:holder:{uuid4()}", name=name, family="PRIVATE_FOUNDATION",
        scope_type="HOLDER", holder="PRIVATE_FOUNDATION", organisation=body, agreement="AGREED",
        served=True,
    )


def test_only_programmes_on_a_recognised_bound_domain_are_admitted(profile, gate) -> None:
    admitted = evidence_program("https://www.tum.de/msc")
    recognise(make_body("tum.de"), "tum.de")
    evidence_program("https://www.unknown-uni-fixture.de/msc")
    make_body("unknown-uni-fixture.de")
    evidence_program("https://www.tum.de/a", "https://blogs.tum.de/b")  # not institutional
    assert [p.id for p in candidate_pool(profile, limit=50).programs] == [admitted.id]


def test_a_fake_page_naming_tum_is_not_admissible_and_tums_own_programme_is(profile, gate) -> None:
    real = evidence_program("https://www.tum.de/msc")
    fake = evidence_program("https://tum-admissions.com/msc", institution=real.institution)
    recognise(make_body("tum.de"), "tum.de")
    make_body("tum-admissions.com")
    ids = [p.id for p in candidate_pool(profile, limit=50).programs]
    assert real.id in ids and fake.id not in ids


def test_a_joint_programme_on_a_recognised_partners_domain_is_admitted(profile, gate) -> None:
    joint = evidence_program("https://www.unibo.it/emjm", joint=True)
    recognise(make_body("unibo.it"), "unibo.it", "funder_list")
    assert [p.id for p in candidate_pool(profile, limit=50).programs] == [joint.id]


def test_the_limit_is_never_spent_on_gated_rows(profile, gate) -> None:
    for key in ("a1", "a2", "a3"):
        gated = evidence_program(f"https://www.gated-{key}-fixture.de/msc")
        Program.objects.filter(id=gated.id).update(canonical_key=key)
    admitted = evidence_program("https://www.tum.de/msc")
    Program.objects.filter(id=admitted.id).update(canonical_key="z9")
    recognise(make_body("tum.de"), "tum.de")
    assert [p.id for p in candidate_pool(profile, limit=1).programs] == [admitted.id]


def test_only_holder_awards_of_a_recognised_funder_are_admitted(profile, gate) -> None:
    good = make_body("daad.de", kind="NATIONAL_GOVERNMENT")
    recognise(good, "daad.de", "curated_list")
    shown = _award(good)
    _award(make_body("daad-scholarships.org", kind="PRIVATE_FOUNDATION"), name="Lookalike")
    assert [a.id for a in candidate_pool(profile, limit=50).awards] == [shown.id]


def test_an_award_with_no_holder_body_is_excluded_and_coded(profile, gate) -> None:
    orphan = _award(None, name="Orphan")
    assert orphan not in candidate_pool(profile, limit=50).awards
    assert provenance_of_award(orphan) == (None, "no_holder_body")


def test_waiting_bodies_are_pending_and_the_empty_reason_says_so(profile, gate) -> None:
    evidence_program("https://www.tum.de/msc")
    tum = make_body("tum.de")
    result = candidate_pool(profile, limit=50)
    assert result.programs == ()
    assert result.pending_bodies == (tum.id,)
    assert "still being checked" in result.empty_reason
    assert "No programme" not in result.empty_reason


def test_with_the_gate_off_the_pool_is_unchanged(profile) -> None:
    unknown = evidence_program("https://www.unknown-uni-fixture.de/msc")
    result = candidate_pool(profile, limit=50)
    assert [p.id for p in result.programs] == [unknown.id] and result.pending_bodies == ()


def test_provenance_of_program() -> None:
    admitted = evidence_program("https://www.tum.de/msc")
    tum = make_body("tum.de")
    assert provenance_of_program(admitted) == (tum.id, "not_evaluated")
    recognise(tum, "tum.de")
    assert provenance_of_program(admitted) == (tum.id, "register")
    split = evidence_program("https://www.tum.de/a", "https://www.lmu.de/b")
    assert provenance_of_program(split) == (None, "evidence_off_domain")
    blog = evidence_program("https://www.tum.de/c", "https://blogs.tum.de/c")
    assert provenance_of_program(blog) == (tum.id, "evidence_off_domain")


@pytest.mark.django_db(transaction=True)
def test_the_pack_build_writes_codes_and_pending_bodies(agency_a, membership_a, settings) -> None:
    settings.PROVENANCE_GATE_ENFORCED = True
    program, award = _catalogue()
    attach_evidence(program, "https://www.tum.de/msc")
    tum = make_body("tum.de")
    recognise(tum, "tum.de")
    recognise(award.organisation, "example-foundation.org", "curated_list")
    waiting, _ = _catalogue(with_award=False, program_name="MSc Computer Science Two")
    attach_evidence(waiting, "https://www.lmu.de/msc")
    lmu = make_body("lmu.de")
    run = _full_run(agency_a, membership_a)
    with tenant_scope(agency_a.id):
        handle_research_message(_message(agency_a, run), rates=EUR_RATES)
        codes = {
            c.program_name: (c.provenance_reason_code, c.provenance_body_id)
            for c in RecommendationCandidate.objects.filter(run=run)
        }
        run.refresh_from_db()
    assert codes["MSc Computer Science"] == ("register", tum.id)
    assert codes["Foundation Stipend"] == ("curated_list", award.organisation_id)
    assert "MSc Computer Science Two" not in codes
    assert run.pending_bodies == [lmu.id]


def test_the_pack_says_how_many_are_still_being_checked_without_the_catalogue(
    agency_a, membership_a
) -> None:
    run = make_run(agency_a, membership_a)
    candidate = make_db_candidate(agency_a, run)
    make_published_pack(agency_a, run, (candidate,))
    with tenant_scope(agency_a.id):
        type(run).objects.filter(id=run.id).update(pending_bodies=[uuid4(), uuid4()])
        with reads_no_catalogue():
            context = _pack_context(membership_a)
    assert context["pending_count"] == 2
```

- [ ] **Step 2: Run them to verify they fail**

Run: `POSTGRES_DB=tehsil_provenance_gate uv run pytest tests/funding/test_pool_gate.py -q --create-db`
Expected: FAIL with `ImportError: cannot import name 'provenance_of_award'`.

- [ ] **Step 3: Implement**

Append to `apps/research/provenance.py`. Add `from uuid import UUID` and `from typing import TYPE_CHECKING`, extend the models import with `OrganisationDomain`, and add `if TYPE_CHECKING: from apps.funding.models import FundingOpportunity, Program`.

```python
def _verdict_row(organisation_id: UUID) -> tuple[str, str]:
    row = (
        ProvenanceVerdict.objects.filter(organisation_id=organisation_id)
        .values_list("reason_code", "bound_domain")
        .first()
    )
    return row if row is not None else (Reason.NOT_EVALUATED, "")


def provenance_of_program(program: Program) -> tuple[UUID | None, str]:
    """The tenant copy for a programme candidate: its evidence body and code.

    Admissible means the body is RECOGNISED, bound to THIS evidence domain, and
    all the evidence is institutional (spec §3) -- exactly the pool's filter.
    """
    if not program.evidence_domain:
        return None, Reason.EVIDENCE_OFF_DOMAIN
    organisation_id = (
        OrganisationDomain.objects.filter(registrable_domain=program.evidence_domain)
        .values_list("organisation_id", flat=True)
        .first()
    )
    if organisation_id is None:
        return None, Reason.NOT_EVALUATED
    code, bound = _verdict_row(organisation_id)
    if code in RECOGNISED_REASONS and not program.evidence_institutional:
        return organisation_id, Reason.EVIDENCE_OFF_DOMAIN
    if code in RECOGNISED_REASONS and bound != program.evidence_domain:
        return organisation_id, Reason.NO_DOMAIN_BINDING
    return organisation_id, code


def provenance_of_award(award: FundingOpportunity) -> tuple[UUID | None, str]:
    if award.organisation_id is None:
        return None, Reason.NO_HOLDER_BODY
    return award.organisation_id, _verdict_row(award.organisation_id)[0]
```

Rewrite `apps/funding/pool.py`'s `candidate_pool` and `PoolResult`. Keep the module docstring, and add one more rule to its "Two rules here DO survive" list: "It never admits a body that is not RECOGNISED (institution provenance gate spec §7.2): the filter sits in the query, before the limit, so gated rows never spend it."

```python
from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from django.conf import settings
from django.db.models import Q, QuerySet

from apps.accounts.schemas import StudentProfileSnapshot
from apps.funding.models import FundingOpportunity, Program
from apps.research.models import Organisation, ProvenanceVerdict
from apps.research.provenance import WAITING_REASONS, Verdict


@dataclass(frozen=True)
class PoolResult:
    programs: tuple[Program, ...]
    #: Served HOLDER awards. An award is an application of its own, never a
    #: discount on a programme (owner decision 2026-09-19).
    awards: tuple[FundingOpportunity, ...]
    #: Why the pool is empty, in words a student reads. Empty when it is not.
    #: P1-7: never a silently short pack -- "we found nothing" and "we did not
    #: look" are indistinguishable to the person waiting for a pack.
    empty_reason: str = ""
    #: Bodies left out because their verdict is not computed yet (spec §7.1).
    #: The run records them; the sweep re-runs the student when one resolves.
    pending_bodies: tuple[UUID, ...] = ()


def _pending(
    programs: QuerySet[Program], awards: QuerySet[FundingOpportunity]
) -> tuple[tuple[UUID, ...], int]:
    """(bodies with no computed verdict yet, how many rows wait on them)."""
    waiting = Organisation.objects.filter(
        Q(provenance__isnull=True) | Q(provenance__reason_code__in=WAITING_REASONS)
    )
    waiting_domains = waiting.values("domains__registrable_domain")
    rows = (
        programs.filter(evidence_domain__in=waiting_domains).count()
        + awards.filter(organisation__in=waiting).count()
    )
    bodies = waiting.filter(
        Q(domains__registrable_domain__in=programs.values("evidence_domain"))
        | Q(fundingopportunity__in=awards)
    ).values_list("id", flat=True).distinct()
    return tuple(sorted(bodies)), rows


def candidate_pool(
    profile: StudentProfileSnapshot, *, limit: int
) -> PoolResult:
    """Programmes and served awards worth evaluating for this student.

    `limit` is required and has no default: an unbounded pool is an unbounded
    evaluation, and every caller should have had to think about the number.
    """
    programs = Program.objects.filter(name__icontains=profile.target_field)
    if profile.excluded_countries:
        programs = programs.exclude(country_code__in=profile.excluded_countries)
    awards = FundingOpportunity.objects.filter(scope_type="HOLDER", served=True)
    # Any suspension at all, on `suspension_quote` rather than a year match on
    # `suspended_for`. The quote is the marker: a suspension naming no intake
    # leaves `suspended_for` blank and is still a suspension (that field's own
    # comment on the model), so the year test said nothing about exactly the
    # case with no year to test. `funding_opportunity_served_not_suspended`
    # now makes served-and-suspended impossible at the database, so this
    # filters nothing in practice -- it is kept, and kept total rather than
    # clever, because the unserve sweep for a withdrawn award that nothing
    # re-reads is still owed (spec section 19).
    awards = awards.filter(suspension_quote="")

    pending: tuple[UUID, ...] = ()
    waiting_rows = 0
    if settings.PROVENANCE_GATE_ENFORCED:
        pending, waiting_rows = _pending(programs, awards)
        recognised = ProvenanceVerdict.objects.filter(verdict=Verdict.RECOGNISED)
        programs = programs.filter(
            evidence_institutional=True, evidence_domain__in=recognised.values("bound_domain")
        )
        awards = awards.filter(organisation__provenance__verdict=Verdict.RECOGNISED)

    # Ordered by a stable key so `limit` takes the same rows on every call. Any
    # deterministic order will do here -- there is no ranking at this stage, and
    # pretending otherwise would put scoring in two places.
    chosen = tuple(programs.order_by("canonical_key")[:limit])
    chosen_awards = tuple(awards.order_by("canonical_key")[:limit])

    reason = ""
    if not chosen and not chosen_awards:
        if pending:
            reason = (
                f"{waiting_rows} programmes or awards are still being checked and will "
                "appear if confirmed."
            )
        else:
            countries = (
                f", excluding {', '.join(sorted(profile.excluded_countries))}"
                if profile.excluded_countries
                else ""
            )
            reason = (
                f"No programme or award in the catalogue matches {profile.target_field} "
                f"for a {profile.intended_intake.year} intake{countries}. "
                "This is what we have read so far, not a statement that none exists."
            )
    return PoolResult(
        programs=chosen, awards=chosen_awards, empty_reason=reason, pending_bodies=pending
    )
```

In `apps/research/spine.py`:
- Add `from uuid import UUID`.
- Add `pending_bodies: tuple[UUID, ...] = ()` as the last field of `SpineResult`, with the comment `#: Bodies the pool left out while their verdict is computed (spec §7.1).`
- Change the empty-pool branch to:

```python
    pool = candidate_pool(profile, limit=POOL_LIMIT)
    if not pool.programs and not pool.awards:
        empty = _empty(pool.empty_reason)
        empty.pending_bodies = pool.pending_bodies
        return empty
```

Pass `pending_bodies=pool.pending_bodies` in the final `SpineResult(...)`.

In `apps/research/services.py`:
- Add `from .provenance import provenance_of_award, provenance_of_program`.
- Before the programme candidate's `RecommendationCandidate.objects.create(`, insert `body_id, code = provenance_of_program(program)`, and add `provenance_reason_code=code, provenance_body_id=body_id,` to that `create`.
- Do the same for the award candidate with `provenance_of_award(award)`.
- Before `if packed_any:`, insert:

```python
    if result.pending_bodies:
        # The pack says so, and the sweep re-runs this student when one of
        # these resolves RECOGNISED (spec §7.1): nothing re-issues a pack in place.
        RecommendationRun.objects.filter(id=run.id).update(
            pending_bodies=list(result.pending_bodies)
        )
```

In `apps/funding/views.py`'s `_pack_context`:
- Initialise `pending_count = 0`.
- Inside `if pack is not None:`, set `pending_count = len(pack.run.pending_bodies)`. `run` is a tenant row, not catalogue.
- Return it in the dict: `"pending_count": pending_count`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `POSTGRES_DB=tehsil_provenance_gate uv run pytest tests/funding/test_pool_gate.py tests/funding/test_pool.py tests/funding/test_spine.py tests/research/test_handle_research_message.py tests/tenancy/test_catalog_grants.py -q`
Expected: PASS. `test_catalog_grants.py`'s end-to-end web test proves `_pack_context` still reads no catalogue table, as `runtime_web`.

- [ ] **Step 5: Run the four checks.**

- [ ] **Step 6: Commit**

```bash
git -C /home/orkhan/Desktop/provenance-gate add apps/funding/pool.py apps/research/spine.py apps/research/services.py apps/research/provenance.py apps/funding/views.py tests/funding/test_pool_gate.py
git -C /home/orkhan/Desktop/provenance-gate commit -m "feat(funding): the provenance gate in candidate_pool, tenant copies and the pending line"
```

---

### Task 14: The named-programme path

**Files:**
- Modify:
  - `apps/research/schemas.py`
  - `apps/funding/services.py:156-176,211-247,287-322`
  - `apps/funding/views.py:84-103`
  - `apps/research/provenance_job.py`
  - `apps/research/management/commands/run_research_worker.py`
- Test: `tests/funding/test_named_program_gate.py`

**Interfaces:**
- Consumes: `check_body`, `Deps`, `NAMED_TAG`, `register.record_organisation`, `hosts.*`, `provenance.BLOCKED_REASONS`, `WORDING`, `recognition_note`, `queue.enqueue_research`, `tenant_transaction`.
- Produces:
  - `ResearchMessage.kind` gains `"check_named_program"`
  - `ResearchMessage.candidate_id: UUID | None = None`
  - `apps.research.provenance_job.check_named_url(source_url: str, program_name: str, *, now: datetime, deps: Deps) -> tuple[UUID | None, str]`
  - `apps.research.provenance_job.check_named_program(message: ResearchMessage, *, check: Callable[[str, str], tuple[UUID | None, str]] | None = None) -> None`
  - `run_research_worker.route(message: ResearchMessage) -> None`
  - `resolve_named_program` queues the check on commit
  - `replace_candidate` refuses `BLOCKED` always, and refuses an unchecked candidate when the gate is enforced
  - `_pack_context` adds `"recognition_notes": dict[UUID, str]`

Spec corrections for this task:

- **The site comes from the counsellor, not a resolver.** No name→site resolver exists: `TavilyProvider.candidates` returns ten URLs and deliberately does not choose (its docstring), and choosing by name is the match §5.2 forbids. The site is the counsellor's verified `source_url`, so `resolve_named_program` queues the check, not `consider_named_program`.
- **Placing the programme is a student action.** `replace_candidate` is called by the student (`replace_candidate_view`, `actor=student`). The counsellor's decision is the resolve step. "The counsellor may add an unconfirmed school" means the counsellor resolves it VISIBLE and the student may then place it, with the note shown.

- [ ] **Step 1: Write the failing tests**

Create `tests/funding/test_named_program_gate.py`:

```python
"""The named-programme path (spec §7.4): the web queues, the worker checks,
the web reads the tenant code. No web path reads the catalogue."""

from uuid import uuid4

import pytest
from django.utils import timezone
from pydantic import ValidationError

from apps.funding.models import PackCandidate, RecommendationCandidate
from apps.funding.services import (
    PackCommandError,
    consider_named_program,
    replace_candidate,
    resolve_named_program,
)
from apps.funding.views import _pack_context
from apps.research.blocking import read_mill_list
from apps.research.management.commands import run_research_worker
from apps.research.models import Organisation
from apps.research.provenance_job import Deps, check_named_program, check_named_url
from apps.research.schemas import ResearchMessage
from apps.tenancy.context import tenant_scope
from apps.tenancy.db import tenant_transaction
from tests.conftest import reads_no_catalogue
from tests.funding.conftest import make_db_candidate, make_published_pack, make_run
from tests.research.provenance_helpers import FakeFetch, FakeStore

pytestmark = pytest.mark.django_db


def _pack(agency, student, *, code: str):
    run = make_run(agency, student)
    first = make_db_candidate(agency, run, program_name="MSc One")
    named = make_db_candidate(agency, run, program_name="MSc Named")
    pack = make_published_pack(agency, run, (first,))
    with tenant_scope(agency.id):
        RecommendationCandidate.objects.filter(id=named.id).update(provenance_reason_code=code)
    return pack, first, named


def test_a_blocked_named_programme_is_refused_with_its_reason(agency_a, membership_a) -> None:
    pack, first, named = _pack(agency_a, membership_a, code="mill_list")
    with tenant_scope(agency_a.id), reads_no_catalogue(), pytest.raises(
        PackCommandError, match="cannot be added: On a published list of unaccredited institutions"
    ):
        replace_candidate(pack, first.id, named.id, membership_a)


def test_an_unchecked_programme_waits_while_the_gate_is_enforced(
    agency_a, membership_a, settings
) -> None:
    settings.PROVENANCE_GATE_ENFORCED = True
    pack, first, named = _pack(agency_a, membership_a, code="")
    with tenant_scope(agency_a.id), pytest.raises(PackCommandError, match="still being checked"):
        replace_candidate(pack, first.id, named.id, membership_a)


def test_before_enforcement_an_unchecked_programme_is_placed_as_before(agency_a, membership_a) -> None:
    pack, first, named = _pack(agency_a, membership_a, code="")
    with tenant_scope(agency_a.id):
        new = replace_candidate(pack, first.id, named.id, membership_a)
        assert PackCandidate.objects.filter(pack_version=new, candidate=named).exists()


def test_an_unconfirmed_programme_is_placed_and_the_student_sees_the_note(
    agency_a, membership_a, settings
) -> None:
    settings.PROVENANCE_GATE_ENFORCED = True
    pack, first, named = _pack(agency_a, membership_a, code="absent_from_register")
    with tenant_scope(agency_a.id):
        with reads_no_catalogue():
            replace_candidate(pack, first.id, named.id, membership_a)
            context = _pack_context(membership_a)
    note = context["recognition_notes"][named.id]
    assert note.startswith("Recognition not confirmed: Not found on its country's register")


def test_resolving_a_named_programme_queues_its_check_after_commit(
    agency_a, membership_a, counselor_membership, monkeypatch, django_capture_on_commit_callbacks
) -> None:
    sent: list[ResearchMessage] = []
    monkeypatch.setattr(
        "apps.funding.services.enqueue_research", lambda message, **_kw: sent.append(message)
    )
    run = make_run(agency_a, membership_a)
    pack = make_published_pack(agency_a, run, (make_db_candidate(agency_a, run),))
    with tenant_scope(agency_a.id):
        candidate = consider_named_program(pack, "MSc Energy Engineering", membership_a)
        with django_capture_on_commit_callbacks(execute=True):
            resolve_named_program(
                candidate, eligible=True, reason="Official page read",
                source_url="https://www.kentech.ac.kr/msc", actor=counselor_membership,
            )
        candidate.refresh_from_db()
    assert candidate.provenance_reason_code == ""
    assert [(m.kind, m.candidate_id, m.run_id, m.tenant_id) for m in sent] == [
        ("check_named_program", candidate.id, run.id, agency_a.id)
    ]


def test_a_queue_failure_is_logged_not_raised(
    agency_a, membership_a, counselor_membership, monkeypatch, caplog,
    django_capture_on_commit_callbacks,
) -> None:
    def down(message, **_kw):
        raise RuntimeError("sqs unavailable")

    monkeypatch.setattr("apps.funding.services.enqueue_research", down)
    run = make_run(agency_a, membership_a)
    pack = make_published_pack(agency_a, run, (make_db_candidate(agency_a, run),))
    with tenant_scope(agency_a.id):
        candidate = consider_named_program(pack, "MSc X", membership_a)
        with django_capture_on_commit_callbacks(execute=True):
            resolve_named_program(
                candidate, eligible=True, reason="r", source_url="https://www.kentech.ac.kr/x",
                actor=counselor_membership,
            )
    assert "named-programme check not queued" in caplog.text


def test_the_message_names_its_candidate() -> None:
    with pytest.raises(ValidationError):
        ResearchMessage(kind="check_named_program", tenant_id=uuid4(), run_id=uuid4())
    with pytest.raises(ValidationError):
        ResearchMessage(kind="run_research", tenant_id=uuid4(), run_id=uuid4(), candidate_id=uuid4())


def _deps() -> Deps:
    return Deps(
        fetch=FakeFetch({}), ror_call=lambda url, *, params, headers: {"items": []},
        store=FakeStore(), sources=(), mill_rows=read_mill_list(), bootstrap={},
    )


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://www.bircham.edu/online-mba", "mill_list"),
        ("https://blogs.tum.de/msc", "evidence_off_domain"),
        ("https://tum-msc.github.io/apply", "no_domain_binding"),
    ],
)
def test_the_worker_check_of_a_named_url(url: str, expected: str) -> None:
    body_id, code = check_named_url(url, "MSc Named", now=timezone.now(), deps=_deps())
    assert code == expected
    if expected == "mill_list":
        body = Organisation.objects.get(id=body_id)
        assert "NAMED_PROGRAM" in body.found_via


@pytest.fixture
def named_candidate(agency_a, membership_a):
    run = make_run(agency_a, membership_a)
    return make_db_candidate(agency_a, run, program_name="MSc Named")


@pytest.mark.django_db(transaction=True)
def test_the_worker_writes_the_tenant_code_under_rls(agency_a, named_candidate, rls_enforced_orm) -> None:
    body_id = uuid4()
    seen: list[tuple[str, str]] = []

    def check(url: str, name: str):
        seen.append((url, name))
        return body_id, "absent_from_register"

    check_named_program(
        ResearchMessage(kind="check_named_program", tenant_id=agency_a.id,
                        run_id=named_candidate.run_id, candidate_id=named_candidate.id),
        check=check,
    )
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        row = RecommendationCandidate.objects.get(id=named_candidate.id)
    assert (row.provenance_reason_code, row.provenance_body_id) == ("absent_from_register", body_id)
    assert [name for _url, name in seen] == ["MSc Named"]


def test_the_worker_routes_a_named_check_outside_the_tenant_transaction(monkeypatch) -> None:
    routed: list[str] = []
    monkeypatch.setattr(run_research_worker, "check_named_program", lambda m: routed.append("named"))
    monkeypatch.setattr(
        run_research_worker, "process_research_message", lambda m, handler: routed.append("run")
    )
    run_research_worker.route(ResearchMessage(
        kind="check_named_program", tenant_id=uuid4(), run_id=uuid4(), candidate_id=uuid4(),
    ))
    run_research_worker.route(ResearchMessage(kind="run_research", tenant_id=uuid4(), run_id=uuid4()))
    assert routed == ["named", "run"]
```

- [ ] **Step 2: Run them to verify they fail**

Run: `POSTGRES_DB=tehsil_provenance_gate uv run pytest tests/funding/test_named_program_gate.py -q --create-db`
Expected: FAIL with `ImportError: cannot import name 'check_named_url'`.

- [ ] **Step 3: Implement the message and the worker**

In `apps/research/schemas.py`:
- Change `kind` to `Literal["run_research", "revalidate_source", "check_named_program"]`.
- Add `candidate_id: UUID | None = None` after `snapshot_id`.
- Extend the validator before `return self`:

```python
        if self.kind == "check_named_program" and (self.candidate_id is None or targets):
            raise ValueError("a named-programme check names exactly one candidate and nothing else")
        if self.kind != "check_named_program" and self.candidate_id is not None:
            raise ValueError("only a named-programme check carries a candidate")
```

Append to `apps/research/provenance_job.py`. Add imports: `from apps.funding.models import Program, RecommendationCandidate` (extending the existing funding import), `from apps.tenancy.context import tenant_scope`, `from apps.tenancy.db import tenant_transaction`, `from django.utils import timezone`, `from .hosts import is_hosting_platform, is_institutional_url, registrable_domain`, `from .register import record_organisation`, `from .schemas import ResearchMessage`.

```python
def check_named_url(
    source_url: str, program_name: str, *, now: datetime, deps: Deps
) -> tuple[UUID | None, str]:
    """The verdict for the body behind a counsellor-verified URL (spec §7.4)."""
    domain = registrable_domain(source_url)
    if not domain or is_hosting_platform(domain):
        return None, Reason.NO_DOMAIN_BINDING
    if not is_institutional_url(source_url, domain):
        return None, Reason.EVIDENCE_OFF_DOMAIN
    organisation = record_organisation(
        domain=domain, name=program_name[:300], kind="INSTITUTION", country_code="",
        found_via=NAMED_TAG,
    )
    return organisation.id, check_body(organisation, now=now, deps=deps).reason_code


def check_named_program(
    message: ResearchMessage,
    *,
    check: Callable[[str, str], tuple[UUID | None, str]] | None = None,
) -> None:
    """Worker side of a named programme: read the candidate, compute the
    verdict OUTSIDE any tenant transaction, write the tenant copy the web reads."""
    if message.candidate_id is None:
        raise ValueError("a named-programme check needs a candidate")
    with tenant_scope(message.tenant_id):
        with tenant_transaction(message.tenant_id):
            candidate = (
                RecommendationCandidate.objects.select_related("evidence")
                .filter(id=message.candidate_id, run_id=message.run_id)
                .first()
            )
            if candidate is None:
                logger.warning("named-programme check: no candidate %s", message.candidate_id)
                return
            source_url, name = candidate.evidence.source_url, candidate.program_name
        body_id, code = (
            check(source_url, name)
            if check is not None
            else check_named_url(source_url, name, now=timezone.now(), deps=Deps())
        )
        with tenant_transaction(message.tenant_id):
            RecommendationCandidate.objects.filter(id=candidate.id).update(
                provenance_reason_code=code, provenance_body_id=body_id
            )
```

In `apps/research/management/commands/run_research_worker.py`:
- Add `from apps.research.provenance_job import check_named_program`.
- Replace the inner `handle_message` with a module-level function:

```python
def route(message: ResearchMessage) -> None:
    """A named-programme check computes a catalogue verdict, which must not run
    inside the tenant transaction `process_research_message` opens (spec §7.1);
    every other message keeps its path."""
    if message.kind == "check_named_program":
        check_named_program(message)
        return
    process_research_message(message, handle_research_message)
```

- Pass `handler=route` to `consume_once`.

- [ ] **Step 4: Implement the web side**

In `apps/funding/services.py`:
- Add `import logging`, `from functools import partial`, `from django.conf import settings`, `from apps.research.provenance import BLOCKED_REASONS, WORDING`, `from apps.research.queue import enqueue_research`, `from apps.research.schemas import ResearchMessage`, and `logger = logging.getLogger(__name__)`.
- In `replace_candidate`, after the `VISIBLE` check, insert:

```python
    # The tenant copy the worker wrote (spec §7.4) -- the catalogue is never
    # read on this web path. BLOCKED never enters a pack; an UNCONFIRMED one
    # the counsellor made VISIBLE may, and the student sees the note.
    code = replacement.provenance_reason_code
    if code in BLOCKED_REASONS:
        raise PackCommandError(f"this programme cannot be added: {WORDING[code][0]}")
    if settings.PROVENANCE_GATE_ENFORCED and not code:
        raise PackCommandError("still being checked; try again shortly")
```

- In `resolve_named_program`, change the candidate `update(...)` to also reset the tenant copy: `state=RecommendationCandidate.State.VISIBLE, eligible=eligible, provenance_reason_code="", provenance_body_id=None`.
- After the `AuditEvent.objects.create(...)` line, insert:

```python
    transaction.on_commit(
        partial(_queue_named_check, candidate.tenant_id, candidate.run_id, candidate.id)
    )
```

- Add this module-level function:

```python
def _queue_named_check(tenant_id: UUID, run_id: UUID, candidate_id: UUID) -> None:
    """The worker computes the verdict for the source the counsellor verified
    (spec §7.4); the web never does. A queue outage is logged, and the daily
    sweep re-queues a VISIBLE named candidate still carrying no code."""
    try:
        enqueue_research(
            ResearchMessage(
                kind="check_named_program", tenant_id=tenant_id, run_id=run_id,
                candidate_id=candidate_id,
            ),
            queue_url=settings.RESEARCH_QUEUE_URL,
        )
    except Exception:  # noqa: BLE001 - the sweep retries; the counsellor's decision stands
        logger.exception("named-programme check not queued for candidate %s", candidate_id)
```

In `apps/funding/views.py`:
- Add `from django.db.models import QuerySet` and `from apps.research.provenance import recognition_note`.
- Change `considered: object = RecommendationCandidate.objects.none()` to `considered: QuerySet[RecommendationCandidate] = RecommendationCandidate.objects.none()`.
- Before the `return`, add:

```python
    # Rendered from the tenant copy the worker wrote, never from the catalogue.
    notes = {member.candidate_id: recognition_note(member.candidate.provenance_reason_code) for member in pool}
    notes.update({candidate.id: recognition_note(candidate.provenance_reason_code) for candidate in considered})
```

- Add `"recognition_notes": notes` to the returned dict.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `POSTGRES_DB=tehsil_provenance_gate uv run pytest tests/funding/test_named_program_gate.py tests/funding/test_student_controls.py tests/research/test_queue.py tests/tenancy/test_catalog_grants.py -q`
Expected: PASS.

- [ ] **Step 6: Run the four checks.**

- [ ] **Step 7: Commit**

```bash
git -C /home/orkhan/Desktop/provenance-gate add apps/research/schemas.py apps/research/provenance_job.py apps/research/management/commands/run_research_worker.py apps/funding/services.py apps/funding/views.py tests/funding/test_named_program_gate.py
git -C /home/orkhan/Desktop/provenance-gate commit -m "feat(funding): named programmes are checked by the worker and gated by their tenant code"
```

---

### Task 15: Operator commands print the verdict and refuse `BLOCKED`

**Files:**
- Modify:
  - `apps/research/provenance.py` (adds `programme_verdict`)
  - `apps/documents/management/commands/draft_letter.py:73-78`
  - `apps/documents/document_worker.py:180-198`
- Test: `tests/documents/test_draft_letter_command.py`, `tests/documents/test_document_worker.py`

**Interfaces:**
- Consumes: `provenance_of_program`, `verdict_of`, `WORDING`, `Verdict`.
- Produces: `apps.research.provenance.programme_verdict(program: Program) -> tuple[str, str]`, returning `(verdict, reason_code)`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/documents/test_draft_letter_command.py`:

```python
def _blocked(programme) -> None:
    from apps.funding.models import Program
    from tests.research.provenance_helpers import make_body, recognise

    Program.objects.filter(id=programme.id).update(
        evidence_domain="bircham.edu", evidence_institutional=True
    )
    recognise(make_body("bircham.edu"), "bircham.edu", "mill_list")


def test_a_blocked_programme_gets_no_letter(agency_a, django_user_model) -> None:
    """Spec §7.5: operator commands print the verdict and refuse BLOCKED."""
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "draft-blocked")
        programme = make_program()
        _prompt(programme)
        _blocked(programme)
        with pytest.raises(CommandError, match=r"BLOCKED \(mill_list\)"):
            _run(agency_a, student, programme)
        assert not DocumentDraft.objects.filter(student=student).exists()


def test_the_verdict_is_printed(agency_a, django_user_model) -> None:
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "draft-verdict")
        programme = make_program()
        _prompt(programme)
        assert "provenance: UNCONFIRMED (evidence_off_domain)" in _run(agency_a, student, programme)
```

Append to `tests/documents/test_document_worker.py`:

```python
def test_a_generate_message_for_a_blocked_programme_is_dropped(
    agency_a, membership_a, monkeypatch, caplog, program_factory
):
    from apps.funding.models import Program
    from tests.research.provenance_helpers import make_body, recognise

    programme = program_factory()
    Program.objects.filter(id=programme.id).update(
        evidence_domain="bircham.edu", evidence_institutional=True
    )
    recognise(make_body("bircham.edu"), "bircham.edu", "mill_list")
    monkeypatch.setattr(
        document_worker, "generate_cv", lambda **kwargs: pytest.fail("generated anyway")
    )
    with caplog.at_level("WARNING", logger="apps.documents.document_worker"):
        document_worker.handle_document_work(
            DocumentWorkMessage(
                action="generate", kind=DocumentDraft.Kind.CV, tenant_id=agency_a.id,
                student_id=membership_a.id, programme_id=programme.id,
            )
        )
    assert "DocumentGenerateBlockedProgramme" in caplog.text
    with tenant_scope(agency_a.id):
        assert not DocumentDraft.objects.filter(student=membership_a).exists()
```

- [ ] **Step 2: Run them to verify they fail**

Run: `POSTGRES_DB=tehsil_provenance_gate uv run pytest tests/documents/test_draft_letter_command.py tests/documents/test_document_worker.py -q --create-db`
Expected: FAIL. The blocked programme gets a letter (no `CommandError` raised), and the verdict line is absent.

- [ ] **Step 3: Implement**

Append to `apps/research/provenance.py`:

```python
def programme_verdict(program: Program) -> tuple[str, str]:
    """(verdict, reason) for an operator command (spec §7.5)."""
    _body, code = provenance_of_program(program)
    return verdict_of(code), code
```

In `draft_letter.py`:
- Add `from apps.research.provenance import WORDING, Verdict, programme_verdict`.
- After `prompt = self._prompt(...)`, insert:

```python
            verdict, code = programme_verdict(prompt.programme)
            self.stdout.write(f"provenance: {verdict} ({code})")
            if verdict == Verdict.BLOCKED:
                raise CommandError(
                    f"programme {prompt.programme_id} is BLOCKED ({code}): {WORDING[code][0]}"
                )
```

In `document_worker.py`:
- Add `from apps.research.provenance import Verdict, programme_verdict`.
- After the `if programme is None: ... return` block (still inside `if message.programme_id is not None:`), insert:

```python
            verdict, code = programme_verdict(programme)
            if verdict == Verdict.BLOCKED:
                # Spec §7.5, defence in depth: pack membership is already
                # verdict-filtered, so this fires only for a body blocked after
                # the pack was built. Dropped, not raised, for the same
                # reason as the unknown-programme case above.
                logger.warning(
                    "DocumentGenerateBlockedProgramme programme=%s code=%s student=%s: "
                    "not generated",
                    programme.id, code, message.student_id,
                )
                return
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `POSTGRES_DB=tehsil_provenance_gate uv run pytest tests/documents/test_draft_letter_command.py tests/documents/test_document_worker.py -q`
Expected: PASS.

- [ ] **Step 5: Run the four checks.**

- [ ] **Step 6: Commit**

```bash
git -C /home/orkhan/Desktop/provenance-gate add apps/research/provenance.py apps/documents/management/commands/draft_letter.py apps/documents/document_worker.py tests/documents/test_draft_letter_command.py tests/documents/test_document_worker.py
git -C /home/orkhan/Desktop/provenance-gate commit -m "feat(documents): operator commands print the provenance verdict and refuse BLOCKED"
```

---

### Task 16: The pack sweep

**Files:**
- Create: `apps/research/provenance_sweep.py`, `apps/research/management/commands/provenance_pack_sweep.py`
- Modify: `apps/funding/services.py:156-176` (`_copy_pool` takes a set of exclusions)
- Test: `tests/research/test_provenance_sweep.py`

**Interfaces:**
- Consumes: `_copy_pool`, `auto_publish_pack`, `dispatch_recommendation_run`, `check_named_program`, `ProvenanceVerdict`, `ProvenanceVerdictChange`, the reason sets.
- Produces:
  - `apps.funding.services._copy_pool(source, target, *, exclude_candidate_id: UUID | None = None, exclude_candidate_ids: Collection[UUID] = ())`
  - `apps.research.provenance_sweep.SweepReport(revised, removed, kept, reruns, cleared, named)`
  - `apps.research.provenance_sweep.sweep(*, now: datetime, dispatch=dispatch_recommendation_run, named_check=None) -> SweepReport`
  - The `manage.py provenance_pack_sweep` command

This task follows the spec's `_copy_pool(exclude_candidate_id=)` citation, extended to a collection. One sweep can withdraw several candidates from one pack, and a version per candidate would publish intermediate packs the student never meant to see.

- [ ] **Step 1: Write the failing tests**

Create `tests/research/test_provenance_sweep.py`:

```python
"""Verdict changes inside published packs, and resolved checks (spec §7.1, §7.3).
Proven under rls_enforced_orm: without tenant_scope AND set_local_tenant per
tenant the sweep is legal SQL that finds nothing."""

from datetime import timedelta
from uuid import uuid4

import pytest
from django.utils import timezone

from apps.funding.models import (
    AuditEvent,
    PackCandidate,
    PackVersion,
    RecommendationCandidate,
    RecommendationRun,
)
from apps.research.provenance import record_verdict
from apps.research.provenance_sweep import sweep
from apps.tenancy.context import tenant_scope
from apps.tenancy.db import tenant_transaction
from tests.funding.conftest import make_db_candidate, make_published_pack, make_run
from tests.research.provenance_helpers import make_body, recognise

NOW = timezone.now()


def _pack(agency, student, rows, *, program=None):
    """rows: (programme name, body or None, code the candidate was placed with)."""
    run = make_run(agency, student)
    candidates = []
    for name, body, code in rows:
        candidate = make_db_candidate(agency, run, program_name=name)
        with tenant_scope(agency.id):
            RecommendationCandidate.objects.filter(id=candidate.id).update(
                provenance_body_id=body.id if body else None, provenance_reason_code=code,
                program_id=program.id if program else None,
            )
        candidates.append(candidate)
    return run, make_published_pack(agency, run, tuple(candidates))


def _downgrade(body, reason: str, at) -> None:
    record_verdict(body, verdict="UNCONFIRMED", reason_code=reason, bound_domain=body.primary_domain,
                   evidence={}, now=at, next_check_at=None)


@pytest.fixture
def world(agency_a, agency_b, membership_a, membership_b, program_factory):
    blocked = make_body("bircham.edu")
    recognise(blocked, "bircham.edu", now=NOW - timedelta(days=90))
    record_verdict(blocked, verdict="BLOCKED", reason_code="mill_list", bound_domain="bircham.edu",
                   evidence={}, now=NOW, next_check_at=None)
    downgraded = make_body("downgraded-uni-fixture.de")
    recognise(downgraded, "downgraded-uni-fixture.de", now=NOW - timedelta(days=90))
    _downgrade(downgraded, "lookup_failed", NOW)
    steady = make_body("tum.de")
    recognise(steady, "tum.de")
    programme = program_factory()
    _pack(agency_a, membership_a, [
        ("MSc Blocked", blocked, "register"),
        ("MSc Downgraded", downgraded, "register"),
        ("MSc Steady", steady, "register"),
    ], program=programme)
    _pack(agency_b, membership_b, [("MSc Blocked B", blocked, "register"), ("MSc Steady B", steady, "register")])
    return {"blocked": blocked, "downgraded": downgraded}


def _current(agency) -> PackVersion:
    with tenant_scope(agency.id), tenant_transaction(agency.id):
        return PackVersion.objects.filter(superseded_at__isnull=True, published_at__isnull=False).get()


def _names(agency, pack) -> set[str]:
    with tenant_scope(agency.id), tenant_transaction(agency.id):
        return set(PackCandidate.objects.filter(pack_version=pack).values_list(
            "candidate__program_name", flat=True))


def _no_dispatch(**_kwargs) -> bool:
    raise AssertionError("no re-run expected")


@pytest.mark.django_db(transaction=True)
def test_blocked_is_removed_and_downgraded_is_kept_with_a_note_in_every_tenant(
    world, agency_a, agency_b, rls_enforced_orm
) -> None:
    report = sweep(now=NOW, dispatch=_no_dispatch, named_check=lambda m: None)
    assert (report.revised, report.removed, report.kept) == (2, 2, 1)
    pack_a = _current(agency_a)
    assert pack_a.version == 2
    assert _names(agency_a, pack_a) == {"MSc Downgraded", "MSc Steady"}
    assert [(n["candidate_name"], n["reason_code"], n["action"]) for n in pack_a.change_notes] == [
        ("MSc Blocked", "mill_list", "removed"),
        ("MSc Downgraded", "lookup_failed", "kept"),
    ]
    assert _names(agency_b, _current(agency_b)) == {"MSc Steady B"}
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        withdrawn = RecommendationCandidate.objects.get(program_name="MSc Blocked")
        assert withdrawn.state == RecommendationCandidate.State.REJECTED
        assert AuditEvent.objects.filter(event="candidate.withdrawn", object_id=withdrawn.id).exists()


@pytest.mark.django_db(transaction=True)
def test_a_second_sweep_changes_nothing(world, agency_a, rls_enforced_orm) -> None:
    sweep(now=NOW, dispatch=_no_dispatch, named_check=lambda m: None)
    report = sweep(now=NOW, dispatch=_no_dispatch, named_check=lambda m: None)
    assert (report.revised, report.removed, report.kept) == (0, 0, 0)
    assert _current(agency_a).version == 2


@pytest.mark.django_db(transaction=True)
def test_still_unconfirmed_two_cycles_later_a_catalogue_candidate_is_removed(
    world, agency_a, rls_enforced_orm
) -> None:
    sweep(now=NOW, dispatch=_no_dispatch, named_check=lambda m: None)
    later = NOW + timedelta(days=61)
    report = sweep(now=later, dispatch=_no_dispatch, named_check=lambda m: None)
    assert report.removed == 1
    pack = _current(agency_a)
    assert _names(agency_a, pack) == {"MSc Steady"}
    assert [(n["candidate_name"], n["action"]) for n in pack.change_notes] == [
        ("MSc Downgraded", "removed")
    ]


@pytest.fixture
def named_world(agency_a, membership_a):
    body = make_body("little-known-college.edu")
    recognise(body, "little-known-college.edu", now=NOW - timedelta(days=400))
    _downgrade(body, "absent_from_register", NOW - timedelta(days=300))
    _pack(agency_a, membership_a, [("MSc Counsellor Added", body, "absent_from_register"),
                                   ("MSc Other", None, "register")])


@pytest.mark.django_db(transaction=True)
def test_a_counsellor_added_unconfirmed_programme_is_never_timed_out(
    named_world, agency_a, rls_enforced_orm
) -> None:
    report = sweep(now=NOW + timedelta(days=365), dispatch=_no_dispatch, named_check=lambda m: None)
    assert report.removed == 0
    assert _names(agency_a, _current(agency_a)) == {"MSc Counsellor Added", "MSc Other"}


@pytest.fixture
def pending_world(agency_a, membership_a):
    resolved = make_body("resolved-uni-fixture.de")
    recognise(resolved, "resolved-uni-fixture.de")
    absent = make_body("absent-uni-fixture.de")
    _downgrade(absent, "absent_from_register", NOW)
    waiting = make_body("waiting-uni-fixture.de")
    rerun = make_run(agency_a, membership_a)
    cleared = make_run(agency_a, membership_a)
    with tenant_scope(agency_a.id):
        RecommendationRun.objects.filter(id=rerun.id).update(pending_bodies=[resolved.id, waiting.id])
        RecommendationRun.objects.filter(id=cleared.id).update(pending_bodies=[absent.id, waiting.id])
    return {"rerun": rerun, "cleared": cleared, "waiting": waiting}


@pytest.mark.django_db(transaction=True)
def test_a_body_resolving_recognised_re_runs_its_student(
    pending_world, agency_a, membership_a, rls_enforced_orm
) -> None:
    dispatched: list[tuple] = []

    def dispatch(*, tenant_id, run_id):
        dispatched.append((tenant_id, run_id))
        return True

    report = sweep(now=NOW, dispatch=dispatch, named_check=lambda m: None)
    assert report.reruns == 1
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        rerun = RecommendationRun.objects.get(id=pending_world["rerun"].id)
        cleared = RecommendationRun.objects.get(id=pending_world["cleared"].id)
        new_run = RecommendationRun.objects.get(id=dispatched[0][1])
    assert dispatched[0][0] == agency_a.id
    assert new_run.profile_version_id == rerun.profile_version_id
    assert rerun.pending_bodies == []
    assert cleared.pending_bodies == [pending_world["waiting"].id]


@pytest.fixture
def unchecked_named(agency_a, membership_a):
    run = make_run(agency_a, membership_a)
    candidate = make_db_candidate(agency_a, run, program_name="MSc Named")
    return candidate


@pytest.mark.django_db(transaction=True)
def test_an_unchecked_named_programme_is_re_queued(unchecked_named, agency_a, rls_enforced_orm) -> None:
    seen = []
    report = sweep(now=NOW, dispatch=_no_dispatch, named_check=seen.append)
    assert report.named == 1
    assert [(m.kind, m.candidate_id) for m in seen] == [("check_named_program", unchecked_named.id)]
```

- [ ] **Step 2: Run them to verify they fail**

Run: `POSTGRES_DB=tehsil_provenance_gate uv run pytest tests/research/test_provenance_sweep.py -q --create-db`
Expected: FAIL with `ModuleNotFoundError: No module named 'apps.research.provenance_sweep'`.

- [ ] **Step 3: Implement**

In `apps/funding/services.py`, change `_copy_pool`. Add `from collections.abc import Collection`.

```python
def _copy_pool(
    source: PackVersion,
    target: PackVersion,
    *,
    exclude_candidate_id: UUID | None = None,
    exclude_candidate_ids: Collection[UUID] = (),
) -> None:
    """Copy every surviving pool membership from ``source`` onto ``target``.

    New ``PackCandidate`` rows are inserted directly (bypassing the tenant-scoped
    ``save()`` hook) so ``tenant_id`` is copied explicitly from ``source``.
    """
    excluded = {*exclude_candidate_ids}
    if exclude_candidate_id is not None:
        excluded.add(exclude_candidate_id)
    memberships = PackCandidate.objects.filter(pack_version=source)
    if excluded:
        memberships = memberships.exclude(candidate_id__in=excluded)
    PackCandidate.objects.bulk_create(
        [
            PackCandidate(
                tenant_id=source.tenant_id,
                pack_version=target,
                candidate_id=member.candidate_id,
            )
            for member in memberships
        ]
    )
```

Create `apps/research/provenance_sweep.py`:

```python
"""Verdict changes reach published packs; resolved checks re-run students.

Institution provenance gate spec §7.1 and §7.3. It loops tenants explicitly and
enters BOTH filters for each -- `tenant_scope` for Django's manager and
`set_local_tenant` for Postgres RLS, the shape `execute_due_erasures` uses:
with either missing, the sweep is legal SQL that finds nothing and exits 0.
There was no withdrawn-award handler to reuse (pool.py said the unserve sweep
"is still owed"); this is it, for provenance.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from django.conf import settings
from django.db import transaction

from apps.funding.models import (
    AuditEvent,
    PackCandidate,
    PackVersion,
    RecommendationCandidate,
    RecommendationRun,
)
from apps.funding.services import _copy_pool, auto_publish_pack
from apps.tenancy.context import tenant_scope
from apps.tenancy.db import set_local_tenant
from apps.tenancy.models import Agency

from .dispatch import dispatch_recommendation_run
from .models import ProvenanceVerdict, ProvenanceVerdictChange
from .provenance import RECOGNISED_REASONS, UNCONFIRMED_REASONS, WAITING_REASONS, Reason, Verdict
from .provenance_job import check_named_program
from .schemas import ResearchMessage

_PLACEHOLDER = "https://research.pending.internal/"


@dataclass
class SweepReport:
    revised: int = 0
    removed: int = 0
    kept: int = 0
    reruns: int = 0
    cleared: int = 0
    named: int = 0


def sweep(
    *,
    now: datetime,
    dispatch: Callable[..., bool] = dispatch_recommendation_run,
    named_check: Callable[[ResearchMessage], None] | None = None,
) -> SweepReport:
    report = SweepReport()
    cycle = timedelta(days=settings.PROVENANCE_CYCLE_DAYS)
    for tenant_id in list(Agency.objects.values_list("id", flat=True)):
        with tenant_scope(tenant_id):
            with transaction.atomic():
                set_local_tenant(tenant_id)
                _revise_packs(now=now, cycle=cycle, report=report)
                reruns = _resolve_pending(report)
                unchecked = list(
                    RecommendationCandidate.objects.filter(
                        state=RecommendationCandidate.State.VISIBLE, program__isnull=True,
                        opportunity__isnull=True, provenance_reason_code="",
                    )
                    .exclude(evidence__source_url__startswith=_PLACEHOLDER)
                    .values_list("id", "run_id")
                )
        # Outside the tenant transaction: each opens its own.
        for run_id in reruns:
            report.reruns += bool(dispatch(tenant_id=tenant_id, run_id=run_id))
        for candidate_id, run_id in unchecked:
            (named_check or check_named_program)(
                ResearchMessage(
                    kind="check_named_program", tenant_id=tenant_id, run_id=run_id,
                    candidate_id=candidate_id,
                )
            )
            report.named += 1
    return report


def _action(
    candidate: RecommendationCandidate, verdict: ProvenanceVerdict, *, now: datetime, cycle: timedelta
) -> str | None:
    if verdict.verdict == Verdict.BLOCKED:
        return "removed"
    if verdict.verdict != Verdict.UNCONFIRMED:
        return None
    if candidate.provenance_reason_code in RECOGNISED_REASONS:
        # Kept: an evidence gap is not proof of fraud, and removing a
        # programme a student may be applying to is the costlier mistake.
        return "kept"
    # Only a catalogue candidate times out; a counsellor-added UNCONFIRMED one
    # was placed knowingly, with the note (owner decision).
    catalogue_row = candidate.program_id is not None or candidate.opportunity_id is not None
    if not catalogue_row or candidate.provenance_reason_code not in UNCONFIRMED_REASONS:
        return None
    left = (
        ProvenanceVerdictChange.objects.filter(
            organisation_id=verdict.organisation_id, old=Verdict.RECOGNISED
        )
        .order_by("-at")
        .values_list("at", flat=True)
        .first()
    )
    return "removed" if left is not None and left <= now - 2 * cycle else None


def _revise_packs(*, now: datetime, cycle: timedelta, report: SweepReport) -> None:
    packs = PackVersion.objects.filter(
        published_at__isnull=False, superseded_at__isnull=True
    ).select_related("run")
    for pack in packs:
        members = list(
            PackCandidate.objects.filter(pack_version=pack)
            .select_related("candidate")
            .order_by("candidate__program_name")
        )
        body_ids = {m.candidate.provenance_body_id for m in members if m.candidate.provenance_body_id}
        verdicts = {
            row.organisation_id: row
            for row in ProvenanceVerdict.objects.filter(organisation_id__in=body_ids)
        }
        removed: list[UUID] = []
        notes: list[dict[str, str]] = []
        for member in members:
            candidate = member.candidate
            verdict = verdicts.get(candidate.provenance_body_id) if candidate.provenance_body_id else None
            if verdict is None:
                continue
            action = _action(candidate, verdict, now=now, cycle=cycle)
            if candidate.provenance_reason_code != verdict.reason_code:
                RecommendationCandidate.objects.filter(id=candidate.id).update(
                    provenance_reason_code=verdict.reason_code
                )
            if action is None:
                continue
            notes.append({
                "candidate_name": candidate.program_name, "reason_code": verdict.reason_code,
                "action": action, "at": now.isoformat(),
            })
            if action == "removed":
                removed.append(candidate.id)
        if not notes:
            continue
        new_version = PackVersion.objects.create(
            run=pack.run, version=pack.version + 1, change_notes=notes
        )
        _copy_pool(pack, new_version, exclude_candidate_ids=removed)
        if removed:
            RecommendationCandidate.objects.filter(id__in=removed).update(
                state=RecommendationCandidate.State.REJECTED
            )
            for candidate_id in removed:
                AuditEvent.objects.create(actor=None, event="candidate.withdrawn", object_id=candidate_id)
        auto_publish_pack(new_version)
        report.revised += 1
        report.removed += len(removed)
        report.kept += len(notes) - len(removed)


def _resolve_pending(report: SweepReport) -> list[UUID]:
    reruns: list[UUID] = []
    for run in RecommendationRun.objects.exclude(pending_bodies=[]):
        codes = dict(
            ProvenanceVerdict.objects.filter(organisation_id__in=run.pending_bodies).values_list(
                "organisation_id", "reason_code"
            )
        )
        resolved = {
            body for body in run.pending_bodies
            if codes.get(body, Reason.NOT_EVALUATED) not in WAITING_REASONS
        }
        if not resolved:
            continue
        if any(codes[body] in RECOGNISED_REASONS for body in resolved):
            # A fresh run evaluates afresh and builds its own pack version;
            # the copy step can only drop a candidate (spec §7.1).
            reruns.append(RecommendationRun.objects.create(profile_version_id=run.profile_version_id).id)
            remaining: list[UUID] = []
        else:
            remaining = [body for body in run.pending_bodies if body not in resolved]
        RecommendationRun.objects.filter(id=run.id).update(pending_bodies=remaining)
        report.cleared += len(resolved)
    return reruns
```

A second sweep is a no-op by construction. A removed candidate leaves the pack. A "kept" note needs the candidate's code to still be a RECOGNISED one, and the first sweep overwrote it with the new reason. The two-cycle removal fires once, and then the candidate is gone.

Create `apps/research/management/commands/provenance_pack_sweep.py`:

```python
"""Carry provenance verdict changes into published packs, and re-run students
whose pending checks resolved (spec §7.1, §7.3). Run by provenance_recheck."""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.research.provenance_sweep import sweep


class Command(BaseCommand):
    help = "Carry provenance verdict changes into published packs (spec §7.3)."

    def handle(self, *args: Any, **options: Any) -> None:
        report = sweep(now=timezone.now())
        self.stdout.write(
            f"packs revised {report.revised}, removed {report.removed}, kept with a note "
            f"{report.kept}, re-runs {report.reruns}, pending cleared {report.cleared}, "
            f"named re-checked {report.named}"
        )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `POSTGRES_DB=tehsil_provenance_gate uv run pytest tests/research/test_provenance_sweep.py tests/funding/test_student_controls.py tests/funding/test_pack_service.py -q`
Expected: PASS.

- [ ] **Step 5: Run the four checks.**

- [ ] **Step 6: Commit**

```bash
git -C /home/orkhan/Desktop/provenance-gate add apps/research/provenance_sweep.py apps/research/management/commands/provenance_pack_sweep.py apps/funding/services.py tests/research/test_provenance_sweep.py
git -C /home/orkhan/Desktop/provenance-gate commit -m "feat(research): the provenance pack sweep, proven under row-level security"
```

---

### Task 17: `provenance_recheck` and its daily EventBridge rule

**Files:**
- Create: `apps/research/management/commands/provenance_recheck.py`
- Modify: `infra/template.yaml` (after `ReminderLadderRule`), `tests/infra/test_template.py`
- Test: `tests/research/test_provenance_sweep.py` (command smoke), `tests/infra/test_template.py`

**Interfaces:**
- Consumes: the `provenance_check` and `provenance_pack_sweep` commands.
- Produces: the `manage.py provenance_recheck` command and the `ProvenanceRecheckRule` resource.

- [ ] **Step 1: Write the failing tests**

Append to `tests/research/test_provenance_sweep.py`:

```python
@pytest.mark.django_db
def test_recheck_runs_the_due_checks_then_the_sweep() -> None:
    from io import StringIO

    from django.core.management import call_command

    out = StringIO()
    call_command("provenance_recheck", stdout=out)
    text = out.getvalue()
    assert text.index("checked 0 bodies") < text.index("packs revised 0")
```

In `tests/infra/test_template.py`:
- Add `("ProvenanceRecheckRule", "WorkerTaskDefinition"),` to the parametrize list of `test_the_canary_input_overrides_the_task_definitions_actual_container_name`.
- Append:

```python
# --- The provenance recheck's daily schedule ----------------------------------


def test_the_provenance_recheck_runs_daily_and_ships_enabled(template: Template) -> None:
    """Spec §7.6: without it UNCONFIRMED is never retried and a good school is
    lost silently -- the erasure schedule's failure mode, so it ships enabled."""
    rule = template.resource("ProvenanceRecheckRule")["Properties"]
    assert rule["ScheduleExpression"] == "rate(1 day)"
    assert rule["State"] == "ENABLED"
    target = rule["Targets"][0]
    assert target["EcsParameters"]["TaskDefinitionArn"] == {"Ref": "WorkerTaskDefinition"}
    raw_input = target["Input"]
    body = raw_input["Fn::Sub"] if isinstance(raw_input, dict) else raw_input
    assert json.loads(body)["containerOverrides"][0]["command"] == [
        "python", "manage.py", "provenance_recheck",
    ]
```

- [ ] **Step 2: Run them to verify they fail**

Run: `POSTGRES_DB=tehsil_provenance_gate uv run pytest tests/infra/test_template.py tests/research/test_provenance_sweep.py -q --create-db -k "recheck or canary_input"`
Expected: FAIL with `ProvenanceRecheckRule is not defined in infra/template.yaml` and `Unknown command: 'provenance_recheck'`.

- [ ] **Step 3: Implement**

Create `apps/research/management/commands/provenance_recheck.py`:

```python
"""Daily (spec §7.6): re-check due provenance verdicts, then sweep packs.

Scheduled by ProvenanceRecheckRule on WorkerTaskDefinition (runtime_engine).
Due means: no verdict yet, UNCONFIRMED past its next_check_at, RECOGNISED once
a cycle -- which covers register reloads, vouch links and RDAP.
"""

from __future__ import annotations

from typing import Any

from django.core.management import call_command
from django.core.management.base import BaseCommand

from apps.research.fetch import CATALOG_ROLE_NOTE


class Command(BaseCommand):
    help = "Re-check due provenance verdicts, then carry changes into packs." + CATALOG_ROLE_NOTE

    def handle(self, *args: Any, **options: Any) -> None:
        call_command("provenance_check", stdout=self.stdout)
        call_command("provenance_pack_sweep", stdout=self.stdout)
```

In `infra/template.yaml`, directly after the `ReminderLadderRule` resource, add:

```yaml
  # Daily, and shipped ENABLED (institution provenance gate spec §7.6): an
  # UNCONFIRMED body nothing re-checks is a good school lost in silence, with
  # every screen saying the right thing -- the erasure schedule's failure mode.
  # provenance_recheck runs the due checks, then the pack sweep.
  ProvenanceRecheckRule:
    Type: AWS::Events::Rule
    Properties:
      Description: Re-check due provenance verdicts and carry changes into packs
      ScheduleExpression: "rate(1 day)"
      State: ENABLED
      Targets:
        - Id: provenance-recheck
          Arn: !GetAtt ValidationCluster.Arn
          RoleArn: !GetAtt EventsInvokeEcsRole.Arn
          EcsParameters:
            TaskDefinitionArn: !Ref WorkerTaskDefinition
            LaunchType: FARGATE
            NetworkConfiguration:
              AwsVpcConfiguration:
                Subnets: [!Ref WorkerPrivateSubnetA, !Ref WorkerPrivateSubnetB]
                SecurityGroups: [!Ref WorkerSecurityGroup]
          Input: !Sub |
            {"containerOverrides":[{"name":"worker",
             "command":["python","manage.py","provenance_recheck"]}]}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `POSTGRES_DB=tehsil_provenance_gate uv run pytest tests/infra/test_template.py tests/research/test_provenance_sweep.py -q`
Expected: PASS, including the existing events-role scope test: the rule targets the already-allowed `WorkerTaskDefinition`.

- [ ] **Step 5: Run the four checks.**

- [ ] **Step 6: Commit**

```bash
git -C /home/orkhan/Desktop/provenance-gate add apps/research/management/commands/provenance_recheck.py infra/template.yaml tests/infra/test_template.py tests/research/test_provenance_sweep.py
git -C /home/orkhan/Desktop/provenance-gate commit -m "feat(infra): provenance_recheck runs daily on the worker"
```

---

### Task 18: Corrections to recorded documents, CLAUDE.md and the runbook

**Files:**
- Modify:
  - `apps/research/closed_lists.py:8-13` (docstring)
  - `apps/research/models.py:62-68` (`Organisation.Status.CANDIDATE` comment)
  - `docs/superpowers/specs/2026-08-31-institution-safety-screen-design.md:272-274`
  - `docs/superpowers/plans/2026-09-25-enumerators.md:800-805,2083`
  - `docs/superpowers/specs/2026-09-22-funding-search-engine-master-design.md:236` and the `### 7.6 Refresh` and `### 9.3 Cadence, expiry, cost` headings
  - `CLAUDE.md` ("The institution-safety screen was removed" section)
  - `docs/runbooks/deploy.md`
- Test: none new. This task changes documentation and comments only. Its checks are the grep in Step 2 and the four checks.

**Interfaces:** none.

- [ ] **Step 1: Make the edits**

1. **`apps/research/closed_lists.py`.** Replace the docstring lines:

```
  list we compiled because nobody publishes one (Azerbaijan's TKTA; the
  intergovernmental bodies, spec 19). An adapter-read list (VGM, EACEA,
```

with:

```
  list we compiled because nobody publishes one (the intergovernmental
  bodies, spec 19). Azerbaijan's institutions come from the ministry's list;
  TKTA publishes two NEGATIVE lists as JSON (not recognised; high refusal)
  and still no list of recognised institutions (provenance gate spec §9.6).
  An adapter-read list (VGM, EACEA,
```

2. **`apps/research/models.py`.** Replace:

```
        #: Search, inventory, a hub page or a pointer found it; fetched and
        #: classified; vouched by no register. Visible to students exactly as a
        #: REGISTERED one is -- status governs spend and dedupe, never what a
        #: student sees.
```

with:

```
        #: Search, inventory, a hub page or a pointer found it; fetched and
        #: classified; vouched by no register. Status governs spend and dedupe
        #: only. What a student sees is decided by the body's provenance
        #: verdict (ProvenanceVerdict; 2026-09-26 gate spec §4, §15), never by status.
```

3. **The safety-screen spec.** Directly after the `- **Azerbaijan.** ...` bullet, which ends with `clear.`, add this indented line:

```
  *Corrected 2026-09-26 (institution provenance gate spec §9.6):* TKTA does publish two negative
  lists as JSON -- not-recognised universities (`/api/not-recognized-universities`) and
  high-refusal universities (`/api/rejected-universities`) -- though still no list of recognised
  institutions.
```

4. **The enumerators plan.** In the quoted docstring at lines 800-805, apply the same replacement as edit 1. On line 2083, replace `§6.2 records that TKTA publishes no list` with `§6.2 recorded that TKTA publishes no list; corrected 2026-09-26: TKTA publishes two negative lists as JSON (not recognised; high refusal) and no list of recognised institutions -- provenance gate spec §9.6`.

5. **The master spec.**
   - On line 236, replace `Azerbaijan's TKTA publishes no list` with `Azerbaijan's TKTA publishes no list of recognised institutions, only two negative lists as JSON -- corrected 2026-09-26, provenance gate spec §9.6`.
   - Directly under `### 7.6 Refresh`, and again directly under `### 9.3 Cadence, expiry, cost`, add:

```
> **Superseded for programme pages, 2026-09-26.** The refresh cadence for programme pages is the
> institution provenance gate spec's §10: once per programme per cycle after it opens (twice for
> two intakes), again when it enters a pack if the last check is stale, and about 30 and 7 days
> before the student's deadline. Firecrawl monthly monitors stay off. Funder award pages keep
> this section.
```

6. **`CLAUDE.md`.** At the end of the section "## The institution-safety screen was removed — 2026-09-14, and this is the record" (before "## Two browsers, two opposite security models"), add:

```markdown
### Recognition returns behind the provenance gate — 2026-09-26

Owner decision, 2026-09-26: recognition returns, to keep fake universities from students and to
judge recognition at home in Azerbaijan. This section's condition for bringing registers back ("a
product decision") is met. Registers return as **evidence sources behind a gate**, not as the
deleted screen (`docs/superpowers/specs/2026-09-26-institution-provenance-gate-design.md`, plan
`docs/superpowers/plans/2026-09-26-provenance-gate.md`). The open door above is closed at
`candidate_pool`. A programme is admissible only when its OWN evidence domain
(`Program.evidence_domain`) is a `RECOGNISED` body's bound domain. The `Institution` row and
`Institution.official_website` decide nothing, because they are found by name.

- **The switch is `PROVENANCE_GATE_ENFORCED`, off until `provenance_check --all` has run.**
  Enforced on an empty verdict table, every pack is empty. The order is in `docs/runbooks/deploy.md`.
- **Forward rule (§7.5):** whatever first creates a `portals.Application` checks the candidate's
  tenant copy `provenance_reason_code` and refuses a BLOCKED one. Nothing creates one today.
- **Schedule requirement (§7.6):** `ProvenanceRecheckRule` (daily, `provenance_recheck`) ships
  ENABLED and must stay so before any real student. Without it UNCONFIRMED is never retried and a
  good school is lost silently.
- **The State Programme PDF is the one stated exception to "PDFs go to Firecrawl" (§6):** a data
  table, parsed as bytes through `fetch_data_file` into a reviewed closed list. It is never a page
  read. Not built yet; Plan 2 needs it.
- **Jev goes through OpenRouter** (`apps/research/jev.py`, the one client; `JEV_API_KEY` from
  `OPENROUTER_API_KEY`; `JEV_MODEL` pinned). It only ever vetoes, and it is skipped and recorded
  when unkeyed.
- **Terms found while planning:** HRK Hochschulkompass permits personal use only, so German bodies
  stay `register_not_loaded` until the Stiftung grants permission. Korea's register needs no key
  (anonymous JSON, served as `text/html`). A register is read by code only when its closed-list
  terms are `OPEN`.
- **Verify, don't assume:** verdict writes are proven as `runtime_engine` (`role_connection`), and
  the sweep and the named-programme worker through `rls_enforced_orm`, because the test role
  bypasses both.
```

7. **`docs/runbooks/deploy.md`.** After the "Scheduled commands" section, add:

```markdown
## The provenance gate: rollout order (spec §7.7)

Once per environment, as the worker (`DATABASE_ROLE=runtime_engine`), in this order:

1. `manage.py rederive_domains` -- only on a database that held data before the private-suffix fix.
2. `manage.py load_closed_lists`
3. `manage.py verify_list_origins` -- read the output. A reviewed row that does not verify stays
   `unmapped_list_row` until a person fixes its website in the list file.
4. `manage.py provenance_check --all` -- the backfill.
5. Only then add `PROVENANCE_GATE_ENFORCED: "1"` to `WorkerTaskDefinition`'s environment in
   `infra/template.yaml`, in its own reviewed change. Enforced on an empty verdict table, every pack
   is empty.

`ProvenanceRecheckRule` then runs `provenance_recheck` daily. Without `OPENROUTER_API_KEY` in the
worker's secrets, the two content vetoes are recorded as skipped. Add it once Jev's DPA is filed
(spec §13.4).
```

- [ ] **Step 2: Check the corrections landed**

Run:

```bash
cd /home/orkhan/Desktop/provenance-gate
grep -n "Azerbaijan's TKTA; the" apps/research/closed_lists.py docs/superpowers/plans/2026-09-25-enumerators.md
grep -n "Visible to students exactly" apps/research/models.py
grep -c "Superseded for programme pages, 2026-09-26" docs/superpowers/specs/2026-09-22-funding-search-engine-master-design.md
```

Expected: the first two greps print nothing, and the count is `2`.

- [ ] **Step 3: Run the four checks.**

- [ ] **Step 4: Commit**

```bash
git -C /home/orkhan/Desktop/provenance-gate add apps/research/closed_lists.py apps/research/models.py docs/superpowers/specs/2026-08-31-institution-safety-screen-design.md docs/superpowers/plans/2026-09-25-enumerators.md docs/superpowers/specs/2026-09-22-funding-search-engine-master-design.md CLAUDE.md docs/runbooks/deploy.md
git -C /home/orkhan/Desktop/provenance-gate commit -m "docs: record the provenance gate and correct the TKTA and visibility claims"
```
