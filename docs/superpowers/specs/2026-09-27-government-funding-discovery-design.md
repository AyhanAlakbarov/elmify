# Government funding discovery — design

Design, 2026-09-27; revised the same day after an adversarial review (17 findings; §13 records
each and where it is resolved). Owner decisions, in conversation, 2026-09-27:

- **Goal:** discover as much master's funding from governments as exists — the MyStart case
  (Azerbaijan's Ministry of Culture, a scheme no list of ours held) is the bar.
- **Scope:** every level of government. For the student's home country: ministries of every
  sector, their agencies and state funds, state companies, the central bank, provinces and cities.
  For every destination: its scholarship agencies and its embassies in the student's home capital.
- **Students first:** Azerbaijani and Turkish. Adding a home country is data, never code.
- **What counts:** only money that can fund a master's degree — any scholarship, grant, stipend or
  support programme that pays for master's study, and tuition waivers. **No loans.** Not recorded
  at all: conference or short-course travel, research visits, bachelor's-only and PhD-only schemes.
- **Social media is read:** public Facebook, Instagram and Telegram accounts of official bodies.
  A post-only scheme (no official page) **is shown to students, citing the post**.
- **Everything is scraped** through the fetch vendors. No source is read by hand because its reuse
  terms are unread.
- **Post re-checks are on demand**, when a pack including the scheme is built. A deleted post is
  flagged deleted in the database.
- **Special-group conditions** get a one-tap question on the scheme's card, asked only when
  relevant. **The student's agency consultant may see the answers.**

Two readings of those decisions the executor took, to be confirmed by the owner (§12):
**"no loans" keeps bonded and forgivable money** (YLSY's service obligation is how Türkiye's
flagship scheme works), and **the one-tap card excludes special-category data** (disability,
religion, refugee status), which keeps its existing "always a person reviews it" path.

What this supersedes, stated once so nobody re-derives it:

- master spec (`2026-09-22-funding-search-engine-master-design.md`) §6.4, "a social post is a
  POINTER, never provenance" — for an official account's post when no official page exists;
- master spec §6.4's Telegram rule ("the official API only, never a scraped web view", with a
  terms-posture row per channel) — replaced by the owner's "everything is scraped";
- the eligibility spec's "not asked, always review" — for the non-special groups of §7 only;
- `ClosedList.Terms.UNREAD` and the "read by hand, never by an adapter (spec 14)" docstrings;
- the hand-typed `tr_outbound_gov` / `az_outbound_gov` lists (one row each), which become outputs
  of §4.

---

## 1. Why the current state misses MyStart

Measured on master (a67820e5):

1. The government lists are typed by hand and hold one scheme each (YLSY; the State Programme).
2. The Wikidata enumerator lists universities only (`docs/research/wikidata-enumerations.csv`),
   and Wikidata holds **zero** scholarship items for AZ or TR (3,732 for DE) — MyStart has none.
3. Nothing reads a social account; `domains.py` denylists `facebook.com`, `instagram.com`, `t.me`.
4. The reader emits pointer names (`funding_judge.PointerLead`) but **nothing turns a name into a
   lead or a site**: `pipeline.DiscoveryReport.pointer_names` is only printed by `funding_yield`.
   The master spec's "pointers become leads (built 2026-09-18)" is stale.

And a structural one: every route today aims at bodies whose job is education. MyStart's funder is
a culture ministry. So the body list spans every sector (§4.1), and the routes that do not start
from a body (§4.3–4.6) matter as much as the ones that do.

## 2. What exists, what is partial, what is new

| need | state on master | this design |
|---|---|---|
| read a site, keep funding pages, turn a page into a scheme | built: `fetch/site.map_site`, `fetch_page`, `funding_reader` + `funding_judge` | reused |
| text inside images and PDFs | built: Firecrawl `/scrape` OCRs an image fetched by its own URL | reused; social images need a fetch step (§5) |
| pointer name → lead → site | **half built** (names emitted, never used) | **build** (§4.7) |
| name → website | built: `resolver.Resolver` (item 8), `wikidata.find_item` | reused by §4.7 |
| refusing old calls, re-checking, withdrawing | built: `cycle_verification.py`, `validity.cycle_validity`, `withdraw_unread`, `resolution/writers.withdraw_item` | reused |
| nationality and residence | built: `eligibility.py` keys `CITIZENSHIP`, `RESIDENCE` | reused |
| target degree level of a scheme | **absent** (`PRIOR_DEGREE` is the student's own degree) | **build** (§7.1) |
| undecidable condition → a person | built: a consultant task created when the pack publishes (`research/services.py`) | reused; the card goes first (§7.2) |
| human questions | built: resolution queue kinds `SITE_UNKNOWN`, `AWARD_DISPUTED`, `HOST_UNREACHABLE`, `KIND_OR_COUNTRY_UNSURE` | reused; one new kind (§6) |
| government domains | built: `domains.VERIFIED_SECOND_LEVEL` (`gov.tr`, `bel.tr`, `gov.az`, …); **unmerged** `recognition.GOVERNMENT_ZONES` on `claude/provenance-gate-design` | **one list** (§4.1) |
| foreign scholarship agencies | **unmerged** `national_scholarship_agencies.csv` (DAAD, Campus France, SI, Chevening, Stipendium Hungaricum, CSC) | reused and extended |
| funding words per language | **absent** (`cycle-vocabulary.csv` holds cycle/apply terms only) | **build** (§4.2) |
| social reading | **absent** (no Browser Use client) | **build** (§5) |
| pack updates after publish | built: packs are versioned (`_publish(..., version=)`); a published version is immutable | reused (§5.2, §7.2) |

**Prerequisite:** `claude/provenance-gate-design` merges first.

## 3. The answer key — built first, searched online, independent of what it grades

`docs/research/government-funding-answer-key.csv`, about 30 government schemes open to Azerbaijani
or Turkish master's students; MyStart is row one.

- Columns: `scheme`, `funder`, `funder_domain`, `official_url` (or post URL), `checked_on`,
  `found_by` (one of `direct_site`, `gov_portal`, `web_search`, `owner`), `notes`.
- Every row is searched online and its URL fetched live on `checked_on`.
- Found by several independent methods; rows found only by `web_search` are reported separately,
  because the search routes would otherwise be graded on their own output.
- **Matching a finding to a row:** same funder `Organisation` and the scheme confirmed by a person
  in the measurement report (names differ by language, so no automatic string match is trusted).
- The owner reviews the file last and adds what they know. It grows; it is a yardstick, never a
  limit on what is served.

## 4. The routes — all run, measured, and scaled by what they find

### 4.1 The body list

Every government body that could fund master's study, as `Organisation` rows.

- **Home country (AZ, TR):** ministries of every sector (culture, youth and sports, digital
  development, health, agriculture, economy, education, …), their subordinate agencies and state
  funds, state companies, the central bank, provinces and cities.
- **Destination side:** each destination's scholarship agencies and its embassies in Baku and
  Ankara.

Sources, in order of trust: the official government directories (read through the vendors), the
agency list, and Wikidata enumeration rows (class × country × `P856`; each class QID and its
min/max count bound is measured when the row is written, as the existing rows were).

**One list of government domains.** `domains.VERIFIED_SECOND_LEVEL` (master) and
`recognition.GOVERNMENT_ZONES` (provenance branch) become one list with one citation per zone.
`gov.az` and `bel.tr` are already on master's; the provenance branch's citations move onto it.

**Bodies that do not own a domain.** Embassies publish under a foreign ministry's domain
(`baku.diplo.de`, `az.diplomatie.gouv.fr`, a path of `gov.uk`). Such a body is identified by
**domain plus path prefix** (a new `OrganisationDomain` shape: `registrable_domain` +
`path_prefix`, empty for today's rows), so the UK embassy is not collapsed into one "gov.uk" body.

**A body with no website at all is out of scope** in this build: `Organisation.primary_domain` is
required, and nearly every government body has a site. Named residual.

**Renamed or merged bodies** keep one `Organisation` with several `OrganisationDomain` rows; a
Wikidata "replaced by" link (P1366) or a directory change is the trigger.

**City governments** (Türkiye ≈ 1,400): the first sample is the ten largest cities by population
in each country; the rest wait on the sample's yield (§8).

### 4.2 Reading each body's website

Map the site; keep pages whose address or title carries a **funding word** in the page's
language; read them with the funding reader. A site that does not answer becomes a
`HOST_UNREACHABLE` resolution item, never "no schemes".

**Funding words** are a new role in `docs/research/cycle-vocabulary.csv` (`funding`), sourced from
Wikidata's labels of scholarship (Q188823), grant and tuition-waiver items in each language, plus
the terms verified on the answer key's pages. Languages: az, tr, **ru** (Azerbaijani government
sites and channels publish in Russian), en, and each destination's language as its agencies are
added.

**Agency hosts that are also catalogues.** `daad.de` and `campusfrance.org` sit in
`domains._ROUTING` (a catalogue of other people's programmes) and are also funders. Rule: a page on
a routing host is citable **for the host's own schemes** when the host is on the reviewed agency
list; programme listings on it stay routing-only.

### 4.3 Gazettes

Resmî Gazete (`resmigazete.gov.tr`, a daily issue) and Azerbaijan's legal database (e-qanun.az,
which serves an empty shell to a plain client, so it is read through the rendering vendor rung).
Read weekly; an entry whose title or text carries a funding word is fetched and read.

- A decree that **creates** a scheme becomes a pointer (§4.7) to its funder.
- A decree that **amends** a scheme triggers a re-read of that scheme's page (the existing
  cycle-verification path); it never edits a row on its own.

### 4.4 The receiving side

- Destination universities' funding pages that name outside funders ("State Programme students",
  "DAAD scholars"): read with the funding reader, whose pointer names feed §4.7.
- Official "study in" portals (already on the catalogue list), read the same way.

### 4.5 Wikidata scheme entries

Instances of scholarship (Q188823) with a sponsor. **Destination side only**: AZ and TR have none.

### 4.6 News and aggregator sites

Read for pointer names only (§4.7); never cited.

### 4.7 Pointers → leads (the missing half, built here)

Every pointer name from any route (§4.3–4.6, and every scheme page read — the snowball) goes:
name → `resolver.Resolver` (Wikidata first, then search) → a `ResearchLead` with
`found_via=POINTER:<host>` and, when a site is found, `record_organisation`; when none is found, a
`SITE_UNKNOWN` resolution item. The pointer's quote is kept with the lead.

## 5. The social reader

**Transport.**
- Facebook and Instagram: the Browser Use service (approved 2026-09-24, master spec §6.4). A client
  is built here: it returns post URL, date, text and image URLs; nothing else crosses the boundary.
- Telegram: the public channel web view (`t.me/s/<channel>`), through the vendor ladder.
- Poster images: platform image URLs expire, so each image is fetched **at read time** by its URL
  through Firecrawl's image path (OCR), and the text stored with the post.

**Which accounts.** An account counts when the **body's own website links to it**. Wikidata
(`P2013` Facebook, `P2003` Instagram, `P3789` Telegram) proposes an account; one Wikidata alone
vouches for is a `KIND_OR_COUNTRY_UNSURE`-style resolution item, because anyone can edit Wikidata.
(Measured: Wikidata carries a Telegram username for 3 of 19 AZ ministries and 0 of 23 TR ones, so
site links are the main source.)

**What is read.** Feed posts only — never stories or reels (they expire), groups, private profiles
or comments. The first read takes 12 months; later reads take new posts only. A post carrying a
funding word goes through the funding reader like a page. **A repost** of another body's call is a
pointer to that body (§4.7), not that body's scheme. **An image-only post** is read through its
image text; with no text at all it is skipped and counted.

**Source rule.** An official page for the scheme, when one exists, is always the cited source. A
post is cited only when none exists (owner). The post-sourced row names **the body** as holder:
the lead carries the body's `Organisation` directly, never derived from the post's host. The
serving check (`funding_reader._served`, today `can_support_claim` by host) accepts a post URL
exactly when it matches a registered account of that `Organisation`.

**Kept:** post link, date, text, image text, and the body. **Never kept:** commenters, reactions,
followers, or any person's profile.

**Deadlines.** A post's deadline year comes from the post's own date when the text states only a
day and month.

### 5.1 New tables (catalogue)

`SocialAccount` (organisation, platform, handle, vouched_by `site_link|resolved`, first_seen) and
`SocialPost` (account, url, posted_at, text, image_text, read_at, state
`live|deleted|unreadable`). Both are **shared catalogue**: `shared_catalog_select`,
`runtime_engine_write` TO runtime_engine, in `_SHARED_TABLES`, a write-denial test through
`runtime_connection`, RLS in the same migration.

### 5.2 The on-demand post check

When a pack is built that holds a post-sourced scheme:

- The pack publishes at once; that scheme's card says **"being confirmed"** (a new card state).
- The check re-fetches the post; the result is reused until 00:00 UTC.
- **Only a positive "gone" signal marks it deleted**: the service's explicit not-found answer (or
  HTTP 404/410). A login wall, an empty page or any error is `unreadable`, which **keeps the
  previous state** — a login wall returns 200 on the same host and must never read as deletion.
- Deleted is not closed: a deleted post takes the scheme down; a call whose deadline passed is the
  existing cycle rule's.
- A changed result publishes the next pack version (packs are immutable per version).
- Rate limit: `rate_limited("post-check", tenant, …)` per tenant per hour, and a daily
  platform-wide check ceiling in settings; a check never re-runs the three readings unless the
  post's text changed.

## 6. Same scheme, found in several places

A ministry's dozens of schemes stay dozens of rows (the reader keys rows on page, heading and kind,
spec 8.7 — unchanged). What is added is a **reversible link**, `SchemeLink` (catalogue table, same
RLS as §5.1), saying two rows are the same scheme:

- **Automatic** only when both rows name the same funder `Organisation` and point at the same
  official URL.
- **Anything fuzzier** (same funder, similar names across languages) becomes a new resolution kind,
  `SAME_SCHEME`, for a person to confirm. Names are never matched by string alone.
- A link is removed by the same queue; rows are never deleted or merged in place.
- Serving shows one card per linked group, citing the official page when a member has one. The
  group is shown while any member is served; `withdraw_unread` still applies per row.
- **Funder vs. administrator:** a scheme paid by one body and run by another (an embassy's quota
  run by the home ministry) keeps the payer as holder and records the administrator as a second
  `Organisation` on the row. `az_bilateral` / `tr_bilateral` rows seed these pairs.

## 7. What counts, and who it is for

### 7.1 Target level and "no loans"

- The reader gains a **target level** label per award track: `MASTER`, `BACHELOR`, `PHD`,
  `ANY` — a new field on `FundingOpportunity`, conditions kept per track. A scheme with no
  `MASTER` or `ANY` track is not written. The State Programme (bachelor's, master's, PhD) is three
  tracks, and only the master's track's conditions reach a master's applicant.
- **Loans:** the reader's `LOAN` rows are no longer written. `FORGIVABLE_LOAN` and bonded
  scholarships (a service obligation, e.g. YLSY) **count** and are shown with the obligation stated
  (the existing return-service disclosure) — confirmation owed by the owner (§12).
- Several intakes a year are several dated calls under one scheme — the existing cycle evidence.

### 7.2 The one-tap card

- **Automatic:** nationality and residence (`CITIZENSHIP`, `RESIDENCE`), and target level.
- **The card** covers these groups, a closed list in code: martyrs' families, veterans' families,
  civil servants, a profession, and a named region (the label carries the region's name, e.g.
  `region:Ganja`, and the card asks "Do you live in Ganja?"; the student's profile holds no
  sub-national residence, so this is never decided automatically). **Special-category conditions (disability,
  religion, refugee status, health) never reach the card**: they keep the existing path, a
  consultant task created when the pack publishes — confirmation owed by the owner (§12).
- **Who assigns a condition to a group:** the reader, as a closed label on the condition, agreed by
  the same three readings as every other label. A condition the readings do not agree on, or that
  fits no group, stays a consultant task.
- Shown only when the student's pack holds such a scheme, on that scheme's card: the funder's own
  sentence, then "Does this apply to you?" — Yes / No / Not sure.
- **Yes** shows the scheme as a match. **No** hides that scheme and every scheme whose condition
  carries the same group label. **Not sure** or no answer keeps today's behaviour.
- An answer publishes the next pack version.
- The card says the funder will check documents. Answers are editable, and asked again after 12
  months.
- **Storage:** `EligibilityAnswer` (student, group, answer, answered_at) — a **tenant** table
  (`TenantScopedModel`, tenant RLS), added to the erasure field set, never sent to any provider,
  never part of any search query. The student's agency consultant may read it (owner).

## 8. Build order, measurement and money

1. `claude/provenance-gate-design` merges; the two government-domain lists become one.
2. The answer key (§3).
3. Shared pieces: funding words (§4.2), pointers → leads (§4.7), target level (§7.1), `SchemeLink`
   and `SAME_SCHEME` (§6).
4. Routes, cheapest first: body list and websites (§4.1–4.2), gazettes (§4.3), receiving side
   (§4.4), Wikidata schemes on the destination side (§4.5), news names (§4.6), social (§5).
5. The one-tap card (§7.2).
6. **Measured on the answer key, per route:** found, found beyond the key, cost per scheme found —
   one table for the owner. Printed and recorded, never asserted by a test (master spec §15).
7. **Scaled by result:** every route stays on; the ones that find more get more budget.

**Money.** Every route runs under a per-run ceiling in settings (search, fetch and model spend
metered as today), and nothing beyond the ten-city sample and the answer-key measurement is billed
without the owner's approval of a figure the sample produced.

## 9. Model calls and their limits

Every new model-calling path follows the reference pattern (data-labelled input, `extra="forbid"`,
capped `max_output_tokens`, `store=False`) and carries `rate_limited()` in the same change: the
funding reader on posts and gazette entries (per body per day), and the on-demand check (§5.2).
No query and no prompt carries a student fact; the card's answers are read only by the pack.

**Anthropic's Usage Policy** lists admissions as high-risk and wants human review before
dissemination. Post-cited rows shown with no human review widen the exposure CLAUDE.md already
records for served funding rows; it stays an open terms question with the others (§12).

## 10. What changes in existing rules

- `domains.py`: the social hosts stay refused as search results and aggregator provenance; an
  **official account** (§5) is readable, and citable when no official page exists.
- Routing hosts on the reviewed agency list are citable for their own schemes (§4.2).
- `ClosedList.Terms.UNREAD` and the "read by hand" docstrings are removed.
- `tr_outbound_gov` / `az_outbound_gov` are regenerated from §4.
- The reader stops writing `LOAN` rows and gains the target-level label (§7.1).

## 11. Out of scope

Loans; money that cannot fund a master's degree; logging in as a person to any platform; stories,
reels, groups, private profiles and comments; government bodies with no website; home countries
beyond Azerbaijan and Türkiye (a later data change).

## 12. Open, and who answers

- **Owner:** that bonded and forgivable money counts (§7.1).
- **Owner:** that special-category conditions stay off the card (§7.2).
- **Owner:** the answer key sign-off (§3) and the spend figure after the sample (§8).
- **Legal, with the existing items:** Browser Use's terms (master spec §6.4) and the Anthropic
  admissions clause (§9).

## 13. Review record (2026-09-27)

| # | finding | resolved in |
|---|---|---|
| 1 | pointer names never became leads | §1, §2, §4.7 |
| 2 | a post could never be served; its holder would be facebook.com | §5 source rule, §5.1 |
| 3 | DAAD / Campus France pages uncitable (routing hosts) | §4.2 |
| 4 | "no loans" would drop YLSY | §7.1, §12 |
| 5 | no target-level mechanism | §7.1 |
| 6 | merge by name reversed spec 8.7 and had no undo | §6 |
| 7 | card: consent, group assignment, immutable packs | §7.2 |
| 8 | "being confirmed" state absent; login wall read as deletion | §5.2 |
| 9 | Telegram web view vs master §6.4 | header, §5 |
| 10 | no Browser Use client; expiring images | §5 transport |
| 11 | tables' RLS, rate limits, cost ceilings | §5.1, §6, §7.2, §8, §9 |
| 12 | embassies on foreign domains; two zone lists; Wikidata-only accounts | §4.1, §5 |
| 13 | no funding words; no Russian | §4.2 |
| 14 | Wikidata schemes empty for AZ/TR | §1, §4.5 |
| 15 | e-qanun.az shell; gazette cadence; amend vs create | §4.3 |
| 16 | vague: classes, groups, regions, sample, timezone, reposts, stories, site down, renames, key matching | §3, §4.1, §5, §5.2, §7.2 |
| 17 | thin Wikidata account coverage | §5 |
