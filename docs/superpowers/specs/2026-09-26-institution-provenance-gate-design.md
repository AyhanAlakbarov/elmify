# Institution provenance gate, and recognition in Azerbaijan — design

Design, 2026-09-26; revised the same day after an adversarial review (22 findings, all resolved
below). Owner decisions, in conversation, 2026-09-26:

- **Year-one catalogue:** it grows only from what discovery finds for students. No catalogue-wide lookup in year one.
- **Fake universities:** they must never reach a student, and no human reviews individual schools.
- **Good funding at little-known schools** must not be lost.
- **Scope:** funding is sought from every country, not a chosen few.
- **Market:** Azerbaijan, so every recommendation says whether the degree can be recognised there.
- **Name-only lists** are used through a **reviewed name→website mapping**, one diff per list change and never per school. This is the existing closed-list mechanism, §4.2.
- **A counsellor may add an unconfirmed school** to a pack, with a visible "recognition not confirmed" note. A blocked school, never.

Figures are measured on 2026-09-26 unless dated otherwise. The scratch data is not in the repo; what must survive is quoted here.

## 1. The problem

`EntityExpansionSource` walks a search-found host, yields claim-capable leads, and
`write_catalog_entry` (`apps/research/catalog.py:416`) mints an `Institution` from any of them.
CLAUDE.md ("The institution-safety screen was removed") names this as the open door. It says a guard must exist before any per-student discovery run carrying a search key. A student-driven catalogue *is* that run.

The review showed the door is wider than CLAUDE.md records:

- **A fake can attach itself to a real university.** `write_catalog_entry` finds the `Institution` by `catalog_key(country, name)`, which is built from the *name* (`catalog.py:451-460`). A fake page that names "Technical University of Munich" lands on TUM's existing row. Any per-institution check would pass it. Joint programmes take their partner list from the page itself.
- **`Institution.official_website` is self-asserted.** It is the minting page's own origin (`catalog.py:458`). `spine._origins` falls back to it when a programme has no evidence claim.
- **Nothing gates what enters a pack.** `pool.candidate_pool` (`apps/funding/pool.py:43`) selects programmes by field with no provenance check (`:51`). It selects HOLDER awards with no institution check (`:59`). `research/models.py:64-67` says a CANDIDATE organisation is "visible to students exactly as a REGISTERED one is".
- **A second way into a pack bypasses the pool.** `consider_named_program` (`funding/services.py:167`) takes a student's free text on a web request. A counsellor then resolves it (`resolve_named_program`), and `replace_candidate` puts it straight into the pack.

## 2. The principle

**Admission rests only on evidence the attacker cannot write.** A fake controls every byte of its own pages. So any check that reads those pages can be fooled by a convincing fake, and a fooled check fails silently. That covers an LLM, Jev, keyword rules, and "looks like a university".

**Content checks may only veto.** A yes lowers the verdict; a no admits nothing. Admission needs an independent authority that names the institution, plus a binding from that authority to a domain. There is **no model call on the admit path**, Jev included.

The first direction taken in conversation was "anchor on ROR". It was measured and failed:

- **7 of 13 institutions on Wikipedia's unaccredited list are active education records in ROR.** They are Bircham International, Atlantic International, Warnborough College (warnborough.ac.uk), Irish International, St Clements, Breyer State and American World University.
- **ROR's own terms** say anyone can request a record, and "an organization does not need to be a legal entity".
- **Restricted TLDs fail too.** Warnborough holds a `.ac.uk` domain, and US `.edu` was grandfathered before 2001.
- **So ROR proves identity, never legitimacy.** It is used below only to bind a recognised body to its domain.

## 3. What is gated: programmes and awards, not institution names

The unit of admission is a **programme** or an **award**. A verdict attaches to a *body*, keyed by domain, never by name.

- **A programme is admissible** when all of its evidence points to one `RECOGNISED` body. The body is found **per programme** from its own evidence, never through the `Institution` row:
  1. take the registrable domain of every `OfficialEvidenceClaim` source URL for the programme;
  2. they must all be the same domain, and that domain must be a `RECOGNISED` body's bound domain;
  3. every evidence URL must sit on that domain's main host or an institutional subdomain.

  **Institutional, not user content.** A subdomain or path that holds user content never counts as evidence. The patterns are the same closed list §5.3 uses: `blog(s).`, `wiki.`, `forum(s).`, `people.`, `users.`, `sites.`, `student(s).`, `~user` paths, and the hosting platforms of §5.6.

  **What never counts:**
  - `Institution.official_website`;
  - the `Institution` row itself, which is still found by name (`catalog.py:451-460`), so it can be reached by a fake naming a real university. It is **not** linked to a body; its name is display only;
  - a programme with no evidence claim, which is not admissible.

  This closes the "fake page naming TUM" hole in both directions:
  - the fake's own programme is not admissible, because its evidence sits on the fake's domain;
  - real TUM programmes are unaffected, because each is judged by its own evidence.

  **Residual risk, accepted by the owner (2026-09-26):** a spam page planted on a *hacked* institutional host of a real university would pass this rule.
  - The `degree_for_payment` veto (§5.4) turns such a page into `UNCONFIRMED(veto_conflict)` when Jev is configured.
  - The earlier "must appear in the institution's own sitemap" condition was dropped. Firecrawl's `/map` includes subdomains and its own index, so it would not close the hole, and it was never measured against real programme pages. Bring it back only after measuring how many real programme pages appear in main-host XML sitemaps.
- **A joint programme** (`institution=None`) is admissible when either holds:
  1. its evidence page is on a `RECOGNISED` partner's bound domain;
  2. it comes from an EACEA `RegisterEntry`, whose partners are bound by PIC and website (`RegisterEntryPartner.Disposition`, existing).
- **A HOLDER award** is admissible when its funder body is `RECOGNISED`. A HOLDER award with `organisation IS NULL` is `UNCONFIRMED(no_holder_body)`.
- **A PROGRAM-scope award** attaches only to an admissible programme (`apps/research/spine.py:135`), so it inherits the check.

**Bodies are `research.Organisation` rows.** They are already keyed by registrable domain through `register.py`'s "never on a name" door. The pool joins a programme to its body through the programme's evidence domain, as `Organisation`'s `OrganisationDomain`.

To keep that join inside the pool query (§7.2), each `Program` stores:
- **`evidence_domain`**: the single registrable domain of its evidence, or empty when its evidence disagrees. It is written by `write_catalog_entry` and by any evidence write, from the evidence URLs, never from the page's name.
- **`evidence_institutional`**, a boolean: whether every evidence URL passes the main-host and user-content rule above.

`funding.Institution` gets no link to a body.

## 4. Verdicts

| verdict | meaning | in packs | retried |
|---|---|---|---|
| `RECOGNISED` | an authority (§5.1) names the body, and its domain is bound (§5.2) | yes | each cycle |
| `UNCONFIRMED` | not established yet, or the evidence disagrees; reason in §4.1 | no, except a counsellor-added one with a note | yes, automatically |
| `BLOCKED` | **positive** evidence of fraud only (§5.4) | never | no |

**Absence is never proof.** A school missing from a register, a website that disagrees with a list, a failed lookup: each gives `UNCONFIRMED`, never `BLOCKED`. That is what keeps a good scholarship at a little-known or newly renamed school from being condemned by a data gap. Both non-admitting verdicts keep a programme out of packs. So `BLOCKED` changes only the wording and stops retries, and it should be rare.

### 4.1 Reason codes (closed enum)

**`RECOGNISED` via:**
- `register`
- `curated_list`
- `funder_list`
- `vouched_by_link`
- `government_zone`

**`UNCONFIRMED` because:**
- `not_evaluated`
- `register_not_loaded`
- `absent_from_register`
- `no_domain_binding`
- `unmapped_list_row`
- `domain_registered_after_listing`
- `veto_conflict`
- `evidence_off_domain`
- `lookup_failed`
- `no_holder_body`
- `vouch_link_missing`
- `no_register` — *added 2026-09-28 (Task 12 fix round 1):* no register is shipped for the body's country, or the body has no country at all. Before this it was `register_not_loaded`, a waiting reason re-checked daily, so a pack said "still being checked" for mit.edu, unibo.it or daad-scholarships.org forever. It is not a waiting reason and is re-checked once per cycle (`PROVENANCE_CYCLE_DAYS`). Wording: "No official register for this country is loaded yet." / "Bu ölkə üçün rəsmi reyestr hələ yüklənməyib." — never recognition.

**`BLOCKED` because:**
- `mill_list`
- `accreditation_mill`
- `fee_to_release_award`
- `degree_for_payment`

The plain-words wording for each code is fixed text, in Azerbaijani and English (§9.4).

## 5. Evidence

### 5.1 Recognition: who may vouch

Any **one** of these is enough. Each source's address is pinned, never found by search:

1. **A country's official register of recognised institutions**, found through ENIC-NARIC.
   - ENIC-NARIC's per-country page (`https://www.enic-naric.net/page-<Country>`) has a "Recognised Higher Education Institutions" section. It has links on 53 of 56 country pages [measured]; examples: Georgia → reestri.eqe.ge; USA → DAPIP and CHEA; Australia → TEQSA.
   - That section is the root of trust for *which* list is official, so a fake "ministry register" cannot insert itself.
   - **Each register actually read** gets one row in `docs/research/closed-lists.csv` (slug, source URL, reuse terms, `carries_website`, verified-on) before the code reads it. Adding a country is a reviewed one-row change, never a per-school step.
   - **Reuse terms are recorded, not a gate** (owner decision, 2026-09-27: "allow everything, as we are using external services"). A register or list whose terms are `UNREAD` or `RESTRICTED` is read by code like an `OPEN` one; the terms column stays as information. This is what ships HRK Hochschulkompass (`RESTRICTED`: personal use only without the Stiftung's permission) and YÖK (`UNREAD`).
   - **Known-answer countries and their registers:**
     - Germany: HRK Hochschulkompass.
     - England: the OfS Register. Scotland is **not** covered by OfS; Scottish degree-awarding bodies come from the Scottish Funding Council's list.
     - Türkiye: YÖK's university list. ENIC-NARIC links studyinturkiye, which is not a register, so YÖK is named by hand. Two pages, one source row each: state universities at `https://www.yok.gov.tr/tr/university?type=1` (128 cards) and foundation universities at `?type=2` (74), each card printing the website (METU → www.metu.edu.tr; measured 2026-09-27).
     - Korea: data.go.kr dataset #15107736. Its 홈페이지주소 field is the website (CLAUDE.md, Web fetching).
     - Azerbaijan: the ministry list `az_heis`, which exists as a reviewed closed list with websites (`docs/research/closed-lists/az_heis.csv`; ASOIU → asoiu.edu.az).
   - **Registers with no data file** (HTML only) are read once per cycle through the vendor ladder (§6).
2. **A reviewed closed list** (`apps/research/closed_lists.py`, `record_list`, existing).
   - A curated list promotes what it names to `REGISTERED`, with the website a person put in the row. That is the owner's "reviewed name→website mapping".
   - Name-only sources become closed lists when a person maps their rows to websites in the diff: the ministry PDFs, the State Programme list, the gov.uk recognised-bodies list.
   - Rows added since the last review are `UNCONFIRMED(unmapped_list_row)` until mapped. Never name-matched.
3. **A funder's own host list**, for the institutions it names:
   - EACEA's project records (PIC per partner, existing adapter).
   - DAAD's database.
   - Azerbaijan's State Programme 2026/27 list: about 276 institutions and 2,907 master's rows, from a 50-page PDF, as a closed list per point 2.
4. **A link from a `RECOGNISED` body's own site**, under §5.3's deterministic rules.

**WHED is not in this design's first plan.** IAU's 2026-09-11 consent covers scraping and access, but not storage or commercial use (§13). The owner decision of 2026-09-27 (terms are recorded, not a gate) unblocks it; it is still not built.

### 5.2 Identity: binding a recognised body to a domain

A binding uses an identifier or a reviewed row, **never a name match**. Measured: affiliation matching paired "The University of Law" with National Law University, Delhi, with `chosen=true`. In order:

1. The website the recognising source lists: a register field, a closed-list `website` column, an EACEA partner website.
2. ROR, through an identifier the source and ROR share, with `apps/research/ror.py::by_domain` (existing; exact `domains:` lookup through `fetch_json_api`, CC0).
   - Compare both `domains[]` and the registrable domain of `links[website]`, because they disagree on 344 records.
   - Measured drift:
     - iu.de sits on a separate record from IU's iu.org;
     - Nyenrode is held under nyenrode.com, not .nl;
     - ESMT's `domains[]` is esmt.org, while its site is esmt.berlin.
3. **Nothing binds** → `UNCONFIRMED(no_domain_binding)`.

**Operating country comes from evidence, never from the page.** Evidence means the register's own country, or ROR. `program_facts.country_code` is a model reading of the attacker's page, so it decides nothing here.

**A branch campus is recognised** when either holds:
1. a register row in its campus country names it;
2. its home country's register names the branch explicitly.

Example of the second: a Dubai free-zone branch licensed by KHDA, which is not on the UAE federal register, passes via its home register's branch entry, or via a KHDA closed list.

### 5.3 Vouching by link: deterministic, one hop, part-of only

Some schools no authority names directly: a constituent institute, a joint-venture campus, a new school under a parent. UFAZ (ufaz.az) is one. It is absent from ROR and is legally part of ASOIU, and asoiu.edu.az's own homepage links to it [measured]. Such a body is `RECOGNISED(vouched_by_link)` when **all** of these hold:

- **A recogniser is chosen by a link, never by a name.** The recogniser is a `RECOGNISED` body whose bound domain the candidate's own site **links to**. The URL's registrable domain is looked up in the bound domains. A parent the candidate only *names* is never resolved; that would be a name match, which §5.2 forbids. The candidate's link is only a pointer to where to look, never evidence. The evidence is the reverse link, below.
- **The link is on the recogniser's main host.** Not a user subdomain, blog, forum, personal page or student site. Hosting platforms (§5.6) never count.
- **The link sits in a structural position:** the recogniser's homepage navigation or footer, or a page within two hops of its homepage whose heading matches a closed list of structural terms. The terms: faculties, schools, institutes, campuses, branches, affiliated institutions, and their Azerbaijani, Turkish, German, French and Korean equivalents, kept in code and pinned by test.
- **Only part-of relationships count.** Pages headed partners, agents, representatives, study abroad, Erasmus, sponsors, alumni, events or news never count. Universities link recruitment agents, exchange partners, online-programme companies and franchise colleges from such pages.
- **One hop only.** A body admitted by link vouches for nothing.
- **Cost is known:** one fetch of the recogniser's homepage, plus at most the structural pages it links (≤ 10 per candidate), through the vendor ladder.
- **Re-checked each cycle.** If the link disappears, the verdict becomes `UNCONFIRMED(vouch_link_missing)` (§7.3).
- **No model call.** Jev is not used on this path.

### 5.4 Blocking: positive evidence only

`BLOCKED` needs one of these:

1. **`mill_list`.** The body's **bound domain**, not its name, is on a pinned mill list:
   - Wikipedia's "List of unaccredited institutions of higher education", pinned to a revision ID and diffed each cycle. A new or removed entry is shown in the operator report, so a vandalised edit is visible.
   - US state lists, where one publishes domains.

   **Override:** only a register of the country the mill list itself names can override it. A mill "recognised" by an unrelated lax jurisdiction stays blocked.
2. **`accreditation_mill`.** The page claims an accreditor that is on a **deny list** of known accreditation mills: a reviewed closed list sourced from CHEA's and USDE's published warnings and the Wikipedia list of unrecognised accreditation associations. There is **no allowlist**: EQUIS, AMBA, AACSB and ABET are real and are on no government list. The accreditor name is picked by code as a verbatim span.
3. **`fee_to_release_award`.** A scholarship page demands a fee **to receive or release the award**. An ordinary application fee is not this; real programmes charge one.
4. **`degree_for_payment`.** The page offers a degree for payment with no study required. "Credit for prior learning" (APEL/RPL) is not this; real universities offer it.

Rules 3 and 4 are veto checks on sentences picked by code. They are Jev yes/no questions if Jev is configured; otherwise they are skipped and recorded as skipped. **Precedence:** a veto hit on a body that is otherwise `RECOGNISED` gives `UNCONFIRMED(veto_conflict)`, not `BLOCKED`. A vendor-language false positive must never condemn a real university. On a body with no recognition, the veto gives `BLOCKED`.

### 5.5 Domain-takeover signal

This catches an expired university domain re-registered by a scammer. It **never blocks**; a legitimate rebrand (esmt.berlin) looks the same.

- **Rule:** if the bound domain's registration date is later than the first date **our own** records saw that domain bound to this body, the verdict is `UNCONFIRMED(domain_registered_after_listing)`. Registers and ROR carry no "website recorded on" date, so our first binding is the only comparable date.
- **The lookup:** RDAP via IANA's bootstrap (`data.iana.org/rdap/dns.json`, 1,202 TLDs, only 71 of them two-letter), calling the registry's base URL directly, since rdap.org redirects.
  - Measured working: .com, .gov, .kr including ac.kr, .uk under Nominet, .fr.
  - No registration date: .az, .de, .tr and ac.uk. DENIC's RDAP gives only a last-changed date; Jisc does not answer Nominet's RDAP.
  - Those are recorded as `skipped`, never as passed. Port-43 WHOIS and the .az web form are **not used**: they would be new outbound paths with no SSRF guard.

### 5.6 The registrable-domain helper, fixed first

`apps/research/hosts.registrable_domain` (`hosts.py:23`) runs tldextract with private suffixes off. Measured:

| host | today it returns | should return |
|---|---|---|
| foo.github.io | github.io | foo.github.io |
| bar.blogspot.com | blogspot.com | bar.blogspot.com |
| tspu.edu.ru | edu.ru | tspu.edu.ru |

So one blog anchors all of blogspot, and one Russian university stands for all of edu.ru. 205 active ROR records, 37 of them education, have their website on a hosting platform: wordpress.com 59, google.com 26, wixsite 23, weebly 20, blogspot 15.

The fix:
- **Private suffixes on.**
- **A never-anchor list of hosting platforms**, pinned by test. A body there can be `UNCONFIRMED`, never `RECOGNISED` through its domain.
- **Re-derive the domain columns:** `OrganisationDomain.registrable_domain`, `primary_domain`, `holder_domain`, `listed_domain`, `contact_domain`.
- **Merged rows:** rows wrongly merged under a platform domain are deleted and re-derived. There is no production database, so no data migration is needed beyond recomputing.

### 5.7 Funders

A funder body is `RECOGNISED` by any of:

- **`government_zone`.** Its registrable domain is on an explicit list of government-only zones. Each entry cites its registry policy:
  - `.gov` (CISA-verified), `gov.uk` (closed list), `gov.az` (state bodies, SCIS), `gov.tr` (public institutions), `go.kr` (government, legislative and judicial bodies), `go.jp`, `gouv.fr`, `gov.cn`, `gob.es`/`gob.mx`, each added with its citation.
  - Plus named single-owner government domains: `europa.eu`, `bund.de`, `bmbf.de`, `auswaertiges-amt.de`, `gc.ca`. The `gc.ca` citation is secondary.
  - A `gov.*` pattern alone is never proof.
- **`curated_list`.** The existing reviewed funder lists, used as evidence per list: `igo_regional_global` (intergovernmental), `az_outbound_gov`, `az_bilateral`, `tr_bilateral`. The funders that fail every other route are added there by a reviewed row: daad.de, campusfrance.org, si.se, chevening.org, stipendiumhungaricum.hu, campuschina.org. A registered association with no open register, like DAAD, is exactly what a curated list is for. `Organisation.Status.REGISTERED` counts as evidence only when it came from `record_list` at rung ≤ 2.
- **A `RECOGNISED` institution,** for university-funded awards.
- **A link from a `RECOGNISED` body** (§5.3).

Blocking uses §5.4 rule 3. A lookalike funder domain (daad-scholarships.org) binds to nothing, and is `UNCONFIRMED` whatever its page says.

## 6. Transports (CLAUDE.md, Web fetching)

| source | transport |
|---|---|
| ENIC-NARIC country pages, HTML registers, the Wikipedia mill list (by revision), recogniser pages for §5.3 | vendor `fetch_page` |
| TKTA JSON, the IANA RDAP bootstrap, registry RDAP answers | `egress.fetch_data_file`, with `application/rdap+json` added to its allowed types |
| CSV/XLSX register files | `fetch_data_file`, with the CSV and XLSX types added. Its global 10 MB cap (`egress.py:16`) becomes a per-call `max_bytes` argument; the default stays 10 MB, and a source's cap is set in its closed-list row. Results are stored to the evidence bucket |
| State Programme PDF | a stated exception to "PDFs go to Firecrawl": it is a data table, parsed as bytes through `fetch_data_file`, which already allows `application/pdf`. Read once per cycle into the reviewed closed list, never into a page read |
| ROR | `ror.py::by_domain`, existing. The 37.5 MB Zenodo dump is **not** used, because `fetch_data_file`'s 10 MB cap rules it out |

## 7. Where it runs, and when

### 7.1 Verdict jobs are separate from pack building

`handle_research_message` is `@transaction.atomic` and locks the run with `select_for_update` (`apps/research/services.py:106-125`). Fetching registers inside it would hold a transaction open across minutes of HTTP; that is the same problem CLAUDE.md records for `read_and_derive`. So:

- **Verdicts are computed by their own worker job,** `provenance_check`, outside any tenant transaction, one body at a time.
- **Pack building only reads verdicts.** A body with no verdict yet (`not_evaluated`), or whose country register is not loaded (`register_not_loaded`), queues a check and is left out of this pack version.
- **Country register loads are serialised** per country with a lease, like `DomainLease`. Two students reaching Germany at once cause one load.
- **When a check resolves, affected students get a fresh recommendation run.** The existing copy step can only drop a candidate, and `handle_research_message` returns early once a run already has a pack version (`services.py:127`). So nothing re-issues a pack in place. Instead:
  - Each pack build records the bodies it left out as pending, in a new tenant field `RecommendationRun.pending_bodies` (a list of organisation IDs).
  - When `provenance_check` resolves a body, the sweep (§7.3) finds runs pending on it, tenant by tenant.
  - If the body resolved to `RECOGNISED`, it dispatches a new run for that student through the existing `dispatch_recommendation_run`, which evaluates afresh and builds a new pack version.
  - If it resolved otherwise, it clears the pending entry.
- **Meanwhile the pack says so.** "N programmes are still being checked and will appear if confirmed." A silently short pack would break the spine's never-silently-short rule, and `pool.empty_reason` must not claim "no programme matches" while checks are pending.

### 7.2 The filter in `candidate_pool`

The verdict filter is part of the query, **before** `order_by(...)[:limit]` (`pool.py:57`), so `POOL_LIMIT` is never spent on gated rows. The filter applies to programmes (§3) and to HOLDER awards (funder verdict). The web tier never computes a verdict.

### 7.3 Verdict changes inside published packs

The sweep command is `provenance_pack_sweep`. There is no existing withdrawn-award handler to reuse (`pool.py:66-68` says the unserve sweep "is still owed"), so it is built here.

- **It loops tenants explicitly,** entering both filters for each one: `tenant_scope` for Django's manager, and `set_local_tenant` for Postgres row-level security. This is the shape `execute_due_erasures` uses (`execute_due_erasures.py:33-42`). With either missing, the sweep would silently find nothing.
- **For every pack containing an affected body** it builds a new version with `_copy_pool(exclude_candidate_id=)`. It appends the note to a new tenant field, `PackVersion.change_notes`: a JSON list of `{candidate_name, reason_code, at}`, shown to the student with that version.
- **`→ BLOCKED`:** removed, with a note "no longer shown: <reason in words>".
- **`RECOGNISED → UNCONFIRMED`:** kept, with a note "recognition could not be re-confirmed on <date>; we are re-checking". The evidence gap is not proof of fraud, and removing a programme a student may be applying to is the costlier mistake. If it is still `UNCONFIRMED` after two further cycles, it is removed with a note.

It is proven through `rls_enforced_orm`, because the test role bypasses RLS.

### 7.4 Named programmes

`consider_named_program` stays a web request that only **queues** a worker job. The worker:
1. resolves the named programme's site through discovery;
2. computes the verdict;
3. writes `provenance_reason_code` onto the tenant `RecommendationCandidate`.

The web page renders the wording from that code; it never reads a catalogue table.

`resolve_named_program` and `replace_candidate` (`apps/funding/services.py:128`) are both web actions. Neither reads the catalogue; both use the candidate's `provenance_reason_code`, written by the worker.
- **`resolve_named_program` shows the code to the counsellor.**
- **`replace_candidate` re-checks it** before putting the programme in the pack:
  - it refuses a `BLOCKED` code;
  - it refuses when no code has been written yet (the check is still running), with "still being checked; try again shortly";
  - on `UNCONFIRMED` it lets the counsellor add it, and the student sees "recognition not confirmed" (owner decision).

### 7.5 Defence in depth

- **`documents/api.py::_programme_id`** already admits only pack or application programmes. Pack membership is now verdict-filtered, so nothing is added there.
- **Whatever first creates a `portals.Application`** checks the tenant copy of the verdict. None exists today, so this is a forward rule recorded in CLAUDE.md.
- **Operator commands** (`draft_letter`, `generate_cv(programme=)`) print the verdict and refuse `BLOCKED`.

### 7.6 Schedule

- **Command:** `provenance_recheck`, run daily by an EventBridge rule on `WorkerTaskDefinition`.
- **What it re-checks:** `UNCONFIRMED` bodies whose `next_check_at` has passed, and `RECOGNISED` bodies once per cycle. That covers register reloads, vouch links and RDAP.
- **After it:** it runs `provenance_pack_sweep`.
- **Before any real student:** the rule must exist, as CLAUDE.md requires for the erasure schedule. Without it, `UNCONFIRMED` is never retried, and a good school is lost silently.

### 7.7 Rollout

1. The first migration creates the tables, with every existing body at `not_evaluated`.
2. A one-off `provenance_check --all` fills them in.
3. **Only then** is the `candidate_pool` filter enabled, behind the setting `PROVENANCE_GATE_ENFORCED`.

Enabling it earlier would empty every pack. There is no production database, so this is about developer and staging databases, and about ordering the plan's tasks.

## 8. Storage

- **`research.ProvenanceVerdict`**, one row per (body, registrable domain) — *changed 2026-09-28 (Task 12 fix round 1) from one-to-one with `research.Organisation`:* a register row recognises the body of its own website, so one body's domains can stand differently. `organisation` is a plain foreign key and `domain` is unique; programmes join on `evidence_domain`, HOLDER awards on `holder_domain`, both to `domain`. The row's `domain` is the bound domain, so the separate `bound_domain` and `first_bound_domain` columns are gone. Fields:
  - `organisation`, `domain`
  - `verdict`
  - `reason_code` (the §4.1 enum)
  - `evidence`, a JSON object:
    - `source_slug`, `source_url`, `list_date`
    - `identifier`: scheme and value
    - `vouch_url`, `admitted_via`
    - `rdap`: status and date
  - `checked_at`, `next_check_at`, `first_bound_at` (for §5.5)
- **`research.ProvenanceVerdictChange`**, append-only: `organisation`, `domain`, `old`, `new`, `reason_code`, `at`. It drives the pack notes and shows bodies whose verdict keeps flipping.
- **Both are catalogue tables.** They follow CLAUDE.md's recipe for a new catalogue table:
  - the standard catalogue read and engine-write policies;
  - `REVOKE ALL` on the tables and their sequences `FROM runtime_web`.

  `tests/tenancy/test_catalog_grants.py` then covers them automatically. Writes are proven as `runtime_engine`.
- **New fields elsewhere:**
  - catalogue side, `Program.evidence_domain` and `Program.evidence_institutional` (§3), written by the engine;
  - tenant side, `RecommendationRun.pending_bodies` (§7.1) and `PackVersion.change_notes` (§7.3). Both are classified in the redaction list and reached by erasure through their pack.
- **Tenant copies on `RecommendationCandidate`:**
  - `provenance_reason_code`;
  - `recognition_outlook`, a JSON list of `{rule_id, result, clause, list_date}` (§9).

  These are written by the worker when the pack is built. Both are classified in the audit redaction list alongside the candidate's other fields, and `test_redaction_classification` enforces it. The reason code is about the institution. The outlook is derived from the student's own answers (§9.3), so it goes with the student's pack on erasure; it is never kept.

## 9. Recognition of the degree in Azerbaijan

A separate question from §4. §4 asks whether this is a real, recognised institution. This asks whether *this student's* degree from it will be recognised at home. It is **advice, not a gate**: a student may still choose a programme whose degree needs conditional recognition. It is shown on every recommendation, because it is the question families ask first. CLAUDE.md records it as the question the deleted register screen never answered.

### 9.1 The authority and the rules

- **Who decides:** TKTA (Təhsildə Keyfiyyət Təminatı Agentliyi), under the Ministry of Science and Education.
- **The rules:** "Xarici dövlətlərin ali təhsilə aid kvalifikasiyalarının tanınması Qaydaları", approved by Presidential Decree of 18 Aug 2023 (No. 2306, per TKTA's FAQ). Its section 4 matches Cabinet Decision No. 34 of 3 Feb 2023, which it replaced.
- **The procedure:** apply at apply.enic.edu.az; the fee is 250 AZN; a decision comes within 3 months.
- **Outcomes:** full, partial, conditional or alternative academic recognition; professional recognition; or refusal with reasons.
- **2025 refusals** (TKTA chair, via a secondary source): 834 in total, of which 495 were for physical presence and 122 for credit differences.

### 9.2 The checks

Each check is tagged with the data it needs. None of them states "will be recognised".

| # | rule (source) | data | shown |
|---|---|---|---|
| 0 | A state degree, not an executive or continuing-education "master's", certificate or MicroMasters (Qaydalar scope; the State Programme excludes executive, distance and non-degree) | programme type | non-degree → "not a degree TKTA recognises"; unknown → a question |
| 1 | Institution accredited and state-licensed in its own country, *institutionally*; a branch's own accreditation counts (§4.1.1; FAQ #25) | the §4 verdict | `register`, `curated_list` or `funder_list` → passes; `vouched_by_link` → "recognised through <parent>; confirm with TKTA"; `UNCONFIRMED` → "not checked yet"; `BLOCKED` never reaches a pack |
| 2 | Not on TKTA's not-recognised list (`GET https://tkta.edu.az/api/not-recognized-universities`, JSON, 64 rows, list dated 2026-06-04 via `/api/dates/1`) | institution, via the reviewed mapping; the student's study years | on it → "on TKTA's not-recognised list"; dated statuses are compared with the study years; unmapped → "not checked" |
| 3 | TKTA's high-refusal list (`/api/rejected-universities`, 53 rows, 30–100%; Russia, Ukraine and Georgia only) | institution, via the mapping | "TKTA refused N% of degrees from here" |
| 4 | Traditional study, at least ⅔ of it; online study without travel never; Türkiye full-time only (§4.1.5; FAQ #2, #22, #26) | study mode from the programme page | online or distance → "not recognisable"; unknown → a question |
| 5 | Physical presence for at least half the normative duration of each year, checked against border records (§4.1.4; FAQ #26) | the student's plans | always shown as a requirement |
| 6 | Credits against Azerbaijan's minimum (90 or 120 ECTS for a master's; below it, conditional only) (§5.5, §5.10) | programme ECTS | below 90 → "conditional: extra credits at an Azerbaijani university"; unknown → a question |
| 7 | Master's field compatible with the bachelor's field (DİM's annual specialisation table; FAQ #76) | the student's bachelor field **as a DİM code**, and the programme field | incompatible → "may not be recognised for your bachelor's field; confirm with TKTA" |
| 8 | Field in Azerbaijan's master's classifier (Cabinet Decision No. 503, 2 Dec 2024), otherwise "alternative" recognition (FAQ #20, §5.11) | programme field as a classifier code | "alternative recognition likely" |
| 9 | Regulated professions (67 fields) need a DİM exam or Ministry of Health check, unless the institution was in the THE, QS or ARWU top 500 in the student's admission year, or the student is State Programme or HTP funded (§6.2–6.4) | programme field, rankings, funding | "exam required" or "exempt" |
| 10 | State Programme eligibility (2026/27 list; offline; no joint or double, executive, distance or non-degree) | institution and programme via the reviewed closed list | "on the State Programme list" (which also exempts from #9) |

**For a consultant, and said so rather than guessed:**
- joint and double degrees (the Qaydalar has no rule);
- how FAQ #26's 21-month total presence applies to a 1- or 2-year master's (it may be bachelor's-only; §13);
- document authenticity.

### 9.3 The student's data

The outlook needs fields the profile does not hold. `_profile_for` returns `None` unless `schema_version == 3` (`apps/research/services.py:98`), so a version bump would empty every pack. The new fields are therefore **optional additions to version 3**:

- **`bachelor_field_code`**: the student picks it from DİM's classifier list at onboarding. It is a list choice, not free text, and no model maps it. Without it, check #7 reads "not checked".
- **`state_funding`**: State Programme, HTP or none.
- **`planned_study_mode`** and **`admission_year`**.

They are student data, so they live on the tenant profile, are reachable by erasure, and are classified in the redaction list. Rows derived from them follow CLAUDE.md's derived-data rule.

Programme-side facts (study mode, ECTS, field) come from the programme page reading that exists today. A fact that was not read is shown as a question to the student, never guessed.

### 9.4 Wording

- **Fixed templates per rule id,** in Azerbaijani and English, pinned by test.
- **Every outlook carries** "TKTA decides; this is our reading of rules published on <date>", and shows each list's date.
- **A list older than one cycle** (TKTA's `/api/dates/1` more than 12 months old, or a failed read) turns that check into "not checked", never "passes".
- **§4.1's refusal wording** is given in both languages the same way.

### 9.5 Sources and their fragility

- **TKTA's JSON endpoints** are the internal API of a Next.js site, with no stated terms. Read them once per cycle through `fetch_data_file`, storing the list date, and treat a failed read as "not checked" (§13).
- **The State Programme PDF:** parsed once per cycle, as in §6.
- **Everything else** is prose rules encoded as the checks above, each citing its clause.

### 9.6 Corrections to earlier documents

TKTA publishes two negative lists as JSON. It still publishes no list of *recognised* institutions. These three documents say otherwise and are corrected in the first plan:

- the 2026-08-31 safety-screen spec §5 ("no list to pre-clear against");
- the 2026-09-25 enumerators plan ("TKTA publishes no list");
- the docstring at `apps/research/closed_lists.py:11` ("TKTA … nobody publishes").

## 10. The student-driven catalogue, and refresh (decisions recorded, not built here)

**Year one.** The catalogue grows only from what discovery finds for students, and a programme found for one student is reused for the next. There is no catalogue-wide lookup or refresh until the catalogue is large. Free official lists may be loaded as names and links, with their pages fetched only when needed.

**Refresh cadence, measured.** The measurement used 29 real pages over 107.7 page-years in the Wayback Machine, 2022–2026. Requirement text changes 0.85 times a year on average (median 0.66); excluding fees, 0.59 (median 0.49). About 66% of changes land around cycle opening, about 20% mid-cycle and about 14% off-season. These are floors, because snapshots are a median of 85 days apart. The cadence that follows:
- once per programme per cycle, after it opens (twice for programmes with two intakes a year);
- again when it enters a pack, if the last check is stale;
- again about 30 and 7 days before the student's deadline.

Firecrawl monthly monitors stay off. The funding spec's §7.6 and §9.3 cadences for programme pages are superseded.

**Per-student discovery cost** needs its own per-student cap before it goes live. `rate_limited()` exists; the cap does not.

## 11. Testing

The test role bypasses grants and RLS. So verdict writes are proven as `runtime_engine`, and tenant copies and the pack sweep through `rls_enforced_orm`. Web rendering of the outlook is proven under `web_role_orm` or `reads_no_catalogue()`, which proves no catalogue read. No test touches the network except the live checks at the end.

The known-answer set has one fixture per outcome and reason. Captured pages and list rows are stored as fixtures.

**Institutions:**
- **`RECOGNISED`:**
  - TUM via Hochschulkompass;
  - Edinburgh via the Scottish Funding Council list;
  - METU via YÖK;
  - UFAZ via a structural link on asoiu.edu.az;
  - KENTECH via data.go.kr (absent from ROR).
- **`UNCONFIRMED`:**
  - Nyenrode (no_domain_binding, until the reviewed row binds nyenrode.nl);
  - a new unmapped list row;
  - an esmt.berlin-style rebrand (domain_registered_after_listing);
  - a Dubai free-zone branch absent from the federal register;
  - a real EQUIS/AMBA business school whose page also carries vendor wording (veto_conflict, never BLOCKED).
- **`BLOCKED`:** the 7 mills in ROR plus Almeda, Rochville, Belford, Ashwood, Selinus and Pacific Western, each by domain; Warnborough (.ac.uk).
- **The TUM impersonation:** a fake page naming TUM on another domain is not admissible, because its evidence is off domain.
- **Hosting platforms:** a blogspot, a wordpress.com and a github.io site can never be `RECOGNISED` by domain.
- **The mill list:** a vandalised Wikipedia revision diff is flagged in the report.

**Wording and fees:**
- APEL wording at a real university: no block.
- An application fee: no block. A fee to release an award: `BLOCKED`.

**Funders:**
- A lookalike funder: `UNCONFIRMED`.
- daad.de via a curated list.
- A `go.kr` funder via its government zone.

**Choke points and sweeps:**
- `candidate_pool` returns no non-admissible programme or HOLDER award, and `POOL_LIMIT` is not consumed by gated rows.
- A named `BLOCKED` programme gives the refusal code. A counsellor-added `UNCONFIRMED` one shows its note.
- `RECOGNISED → UNCONFIRMED` inside a published pack is kept with a note. `→ BLOCKED` is removed.

**Azerbaijan rules:** one test per row of §9.2, citing the clause, including stale-list → "not checked".

**Live checks** (marked `live`, run manually, never in CI): re-read TKTA's endpoints, one ENIC-NARIC page, one register and one RDAP answer, and assert their shape.

## 12. Build order

Two plans, not one, because they fail independently:

**Plan 1, the gate (§3–§8, §11).**
1. The registrable-domain fix and re-derivation.
2. Storage, grants and the rollout setting.
3. Recognition sources:
   - closed lists and funder lists first, since they reuse existing machinery, with the origin-verification step for every row used as evidence (§13.8);
   - the ENIC-NARIC register loader and the known-answer countries' registers;
   - ROR binding.
4. Blocking and vetoes.
5. Vouching by link.
6. RDAP.
7. The `provenance_check` job and the country lease.
8. The `candidate_pool` filter and the "still being checked" line.
9. The named-programme path.
10. The sweep and recheck commands, and their EventBridge rule.
11. Corrections to the documents named in §9.6 and §15.

**Plan 2, the Azerbaijan outlook (§9).** It needs Plan 1's verdict for check #1, and nothing else from it.

§10 is recorded decisions, not work.

## 13. Open questions and blockers

1. **WHED consent.** It does not cover storage or commercial use. Ask IAU. WHED stays out of Plan 1. **Unblocked 2026-09-27** by the owner decision that reuse terms are recorded, not a gate (§5.1); building it is a separate change.
2. **ENIC-NARIC reuse terms.** It has a disclaimer only, and robots.txt blocks only admin and upload paths. It is read once per country per cycle; confirm this is acceptable use.
3. **TKTA endpoints have no terms.** Ask TKTA for a stable source or permission. Meanwhile read politely, once per cycle.
4. **Jev key and DPA.** Not in place. The two veto checks (§5.4 rules 3 and 4) are skipped and recorded until they are. Nothing admits through Jev.
5. **The 21-month presence rule for a master's.** Ask TKTA, or a consultant, before check #5 says anything stronger than "requirement".
6. **Registers for countries outside ENIC-NARIC** (Japan, China and others). Each is added as a reviewed closed-list row when students' searches reach it. Until then those bodies are visibly `UNCONFIRMED(no_register)` (was `register_not_loaded` until 2026-09-28, §4.1).
7. **Korea's register needs a key.** data.go.kr dataset #15107736 is reachable only through its Open API with a service key (CLAUDE.md). Registering for one is the owner's action. Until then, Korean institutions stay `UNCONFIRMED(register_not_loaded)`, KENTECH's known-answer test runs on a captured fixture, and the live check is skipped.
8. **The reviewed name→website mapping must be verified, not just reviewed.** `az_heis.csv` records that its websites came "from search, origin not fetched" (egress was blocked on 2026-09-26). A reviewed row's website counts as admission evidence only once its origin has been fetched and the page names the institution. Until then, the row is `UNCONFIRMED(unmapped_list_row)`. Plan 1 includes that verification step for every closed list used as evidence.
9. **Reuse terms (2026-09-27, owner): recorded, not a gate.** "Allow everything, as we are using external services." No source is refused for its terms; `closed-lists.csv` keeps `reuse_terms` as information. Items 1–3 are no longer blockers on reading.

## 14. Out of scope

- Tenant-added partner schools, such as an agency's commercial partners.
- Recognition at home for markets other than Azerbaijan, for example Türkiye's YÖK equivalence. §9 is the pattern to copy.
- Programme-level accreditation, except as TKTA treats it. Rankings, except where TKTA uses them.

## 15. Changes to recorded decisions

- **CLAUDE.md, "The institution-safety screen was removed":** recognition returns by owner decision on 2026-09-26, to protect students from fake universities and to judge recognition at home in Azerbaijan. That section's condition for bringing registers back, "a product decision", is met. Registers return as evidence sources behind the gate, not as the deleted 737-line screen. The research is reused.
- **`research/models.py:64-67`:** "visible to students exactly as REGISTERED" is replaced. Visibility comes from the verdict.
- **Funding master spec §7.6 and §9.3:** the refresh cadence for programme pages is superseded by §10.
- **CLAUDE.md gains:**
  - the forward rule for the first `Application` creator (§7.5);
  - the schedule requirement (§7.6);
  - the PDF exception for the State Programme list (§6).
