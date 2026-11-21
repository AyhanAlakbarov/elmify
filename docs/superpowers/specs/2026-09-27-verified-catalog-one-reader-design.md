# A verified catalogue on one reader

Design, 2026-09-27. Covers three changes and how to measure them without people:

- where organisations come from and how a website is proven to be theirs;
- a funding reader built on Jev instead of three generative readings (since 2026-10-12: code finders plus two cheap readers, with Opus deciding their disagreements; §0.25, §5);
- which model answers what, and how a single reader is kept honest.

Read with:
- `2026-09-22-funding-search-engine-master-design.md` (the funding engine this plugs into);
- `2026-09-22-typed-decisions-and-multilingual-sources-design.md` (the Jev decision layer, `apps/research/decisions.py`);
- `docs/superpowers/research/2026-09-23-jev-question-engineering.md` (how to write Jev questions);
- `2026-09-23-labelled-corpus-design.md` (the owner-labelled requirement corpus, which this does not replace).

## 0. Owner decisions this design rests on (2026-09-26 and 2026-09-27)

1. **No step waits on a person.** Uncertainty means "not shown", never a queue. *(For the funding reader, the hold queue of item 29 replaces "never a queue". What is held is still not shown.)*
2. **A website is saved only with a recorded proof.** This replaces the resolver's one-time country hold-out as the thing that allows writes.
3. **Paid work runs only when a student needs it.**
   - No scheduled retries.
   - A student meeting an unchecked organisation sees "checking…" for up to about a minute, once.
4. **Launch students are from Azerbaijan.** The destinations are:
   - all EU countries, Norway, Switzerland, Iceland and the UK;
   - Saudi Arabia, UAE, Qatar, Kuwait and Bahrain;
   - Australia, New Zealand, Singapore and Brunei;
   - Serbia, Türkiye, China, Japan, South Korea and Russia;
   - Vietnam, top universities only;
   - the South Caucasus and Kazakhstan;
   - the US and Canada;
   - Africa, South America and Mexico, top universities only.
5. **Exactly one reader per decision in production.** No multi-model vote.
6. **The cheapest model that matches quality answers.** Chinese model families are included, on any host in any country, and student data is included.
   - The owner decided this after being told that content with the identifiers removed is still personal data under GDPR (Recital 26).
   - Direct identifiers are stripped in code before any model call (§6.4).
7. **A source site's terms are not a gate.** Fetching goes through the scraping vendors.
8. **Measurement is built by models, not people, for a few dollars** (§7).
9. **Jev is the only model in the funding reader.** Writing models read no page facts; they write letters and CVs, and serve as the second reader in measurement only. *(Superseded 2026-10-12 by item 25.)*

**Owner decisions of 2026-10-03 (grilling session).** Where they differ from items 1–9 above, these win; the earlier items stay as the record.

10. **Verified only.** A student sees an award only when every value shown on it is verified (§5.5) **and** the student is eligible on verified facts. Nothing unverified reaches a student in any form: no warning badge, no "name + link" note, and a whole language that has not passed stays invisible. Owner: "It shouldn't be shown as it will lower the reputation of a platform. Student should see only programs that he can apply to and verified."
11. **Three mistakes must never happen:** a wrong or missed deadline; telling a student "eligible" when they are not; a wrong document list. Wrongly hiding an award from an eligible student is accepted as rare.
12. **A shown fact is anchored to truth by the owner's own checks**, not by models alone. The owner checks a gold set once before launch through an internal staff page, and again only for what a later change touches (§5.5). This replaces item 8 for certification; the model-built key stays for tuning and for the production audit.
13. **Certified bounds** (95% confidence): at most 1 wrong in 100 on every shown field, precision first (owner, 2026-10-09). This replaced the 2026-10-03 limits (deadlines 1 in 1,000; eligibility and documents 1 in 500). The way to do better is refining wording, questions and prompts as the system runs, not a stricter first bar.
14. **"Verified" needs agreement.** Jev at its measured bar, code checks, and for deadlines, eligibility and documents a second independent reader agreeing (decision engine §3.3, which supersedes item 5's "exactly one reader"). *(Its readers superseded 2026-10-12 by item 25.)*
15. **A core is verified before launch; everything else on first need.** This narrows item 3. Catalogue verification is charged to a platform budget, never to a student's `wallet.py` budget.
16. **One freshness rule** (§5.5) replaces monthly checks, "30 and 7 days before the deadline" and "no schedule". It is driven by the calendar and by student actions.
17. **Gazettes are read weekly on the platform budget** (Resmî Gazete; Azerbaijan's e-qanun.az through the render rung, 25 credits a read). This is the one scheduled *discovery* job, and it narrows item 3.
18. **A body the gate cannot confirm never reaches a student, whoever placed it.** The counsellor path that made an UNCONFIRMED body visible with a "Recognition not confirmed" note is removed. A counsellor who knows a body may submit its official website. That website then goes through the same proof, and is never trusted because a person typed it.
19. **A student may go to any country.** The destination list in item 4 sets the launch's priority, not a limit. How a university is proven anywhere is the lean rule of §4.1 (owner, 2026-10-03, after a brainstorm, two research passes and a live test on eight universities).
20. **An Erasmus Mundus joint master (EMJM) is a programme, never a university's name** (owner, 2026-10-04). It is read from its own site with its mobility path, specialisations and awarded degrees, and shown only while its site states a current or next intake (§3.2).
21. **An EMJM that no longer carries the EU scholarship is shown only to a student who says they can fund themselves** (owner, 2026-10-04).
22. **A student who names a country is asked one more question:** "Would an Erasmus Mundus joint programme that studies in <country> for part of the time be fine for you?" Only a yes lets EMJMs that pass through that country match (owner, 2026-10-04).
23. **A programme a student types in is checked by the agent, verified-only, exactly like a catalogue programme. No counsellor task is created** (owner, 2026-10-04). The student gives its link, or the agent searches and asks the student to confirm the page it found; the link goes through the same proof, and the programme is judged eligible or not, never "possibly" (owner, 2026-10-05; §3.3).

**Owner decisions of 2026-10-08 to 2026-10-12 (slice-2 grilling, plan-3 session).** Where they differ from items 1–23, these win; the earlier items stay as the record. Measurement behind them: `~/agent-workspace/elmify-runs/slice2-spike/` (`README.md`, `v2/`, `hunt/summary.md`).

24. **The reader reads an award, not a line.** The unit is the award, read with its page section: headings, neighbouring lines and links. A cheap line filter may first choose which lines matter, but a line-by-line yes/no is never the final decision (§5).
25. **Two cheap readers, and Opus when they disagree.** DeepSeek V4.1 Flash and GPT-6-luna read every award. When they agree, the value is accepted. When they disagree (about 8% of answers), Claude Opus 5.5 decides. There is no Sonnet, and neither Jev nor Kimi K3 is in the reader; Jev may come back later as a measured filter. The reader list is configuration that every question set and every session reuses, and it stays provisional until round 2 confirms it (§5.5). **This replaces item 9** ("Jev is the only model in the funding reader") **and the reader named in item 14.** Item 14's rule still holds, with code checks first and agreement required, but the agreement is now between DeepSeek and Luna, it covers every field kind, and Opus settles a split (§5.5).
26. **Definitions v3** (§5.2.1):
    - level is the level the award is *for*;
    - a prerequisite degree or an excluded degree is its own condition;
    - year-of-study wording maps to a level through a per-country table;
    - nationality means a named list, and generic "international students" is not a condition;
    - residence limits, stateless persons and compatriots abroad are eligibility conditions;
    - application dates are this award's dates only;
    - a required test or certificate is a requirement.
27. **Country groups: the funder's own list first, then a fixed fallback** (§5.2.1). A group the fallback cannot settle goes to the hold queue.
28. **Precision first, with capped cost and time.**
    - At most 1% wrong per shown field, deadlines included (item 13, unchanged).
    - At most $0.25 of model spend per page. The measured design costs about $0.01–0.02.
    - The background catalogue sweep is bought at batch prices (50% off) and may take hours per page. Only a page a student waits on (a typed programme, an on-demand single-page read) must finish in under 30 s.
    - The first job is the catalogue sweep.
29. **The hold queue** (2026-10-09, recorded here). **It replaces item 1's "never a queue" for the funding reader.** These go to a queue for the platform operator:
    - a fact the site hunt could not find;
    - a conflict the rules cannot settle;
    - a hold-listed country group.

    The award is hidden from every student, B2C included, until the operator acts. The operator fixes the wording (criteria, a finder, an example, a data row) and never a one-off value, then re-runs. At most 15% of real awards may sit in the queue (§5.5 step 6).
30. **Round 2 comes after slice 2.** The owner checks about 250 card values from about 35 fresh pages in 13 languages, with Opus's notes beside each value. It confirms the reader stack and counts how often vague country phrases occur (§5.5).

## 1. Why

- **The funding reader costs about $0.35 a page.** Three generative readings (two OpenAI, one Claude Sonnet 5) must all agree.
  - Claude is most of that cost: $2 / $10 per million tokens.
  - Prices on OpenRouter, 2026-09-27:
    - DeepSeek V4 Pro: $0.35 / $0.70.
    - DeepSeek V4 Flash: $0.047 / $0.094.
    - `gpt-5.6-luna`: $0.20 / $1.20.
    - Jev: $0.042 per million input tokens, output free.
- **Three-way agreement served almost nothing.**
  - The 2026-09-16 run turned 497 EACEA leads into 69 award rows: **5 agreed, 2 served**.
  - The run had no known-answer set, so nothing measured whether a served award was correct (`docs/superpowers/2026-09-16-funding-reader-precision-run.md`).
- **Building the EU catalogue on today's reader costs about $13,000**, almost all of it reading.
- **Once reading is cheap, search (about $0.59 a tap) is the main cost.**

## 2. The shape

```
registers + official scholarship databases + Azerbaijani state lists   (Part A, mostly free)
  -> eligibility pre-filter on the register's own text   (Jev, no fetch)
  -> [pre-built core before launch | a student needs this organisation]
  -> resolver proposes up to 2 websites            (existing)
  -> proof: the provenance gate + register details on the site   (Part B)
  -> funding page -> reader: code finders, DeepSeek + Luna, Opus on a split -> award card   (Part C)
  -> verification: agreement, ladder, certified bars, freshness   (Part F, §5.5)
  -> pack: verified and eligible only
  -> 1 page in 20: audit against a second reader   (Part E)
```

## 3. Part A — where organisations come from

**Per destination country, universities and funders are built together.** Sources, in order:

1. **The official higher-education register** (universities). Where one lists websites, that is the proof (§4, P1).
2. **The government's own directory of its bodies** (ministries, agencies). Where it lists websites, that is the proof. This covers countries whose government sites use ordinary addresses, like `bmbf.de`.
3. **Foundation and charity registers.**
4. **Official national scholarship databases**, for example Campus France's CampusBourses and Study in NL's finder.
   - They list exactly the awards open to international students, so they are the best free list of relevant funders.
   - They are leads, never provenance: award facts still come from the holder's own page. That is the existing `HOPPABLE_CATALOGUES` rule.

**Each source is a `ClosedList`, and each row a `RegisterEntry`** (existing tables). New columns hold what a register prints about a body:
- registration number;
- postal address;
- telephone;
- stated purpose text;
- category code (for example, the US tax register's NTEE `B82`, "scholarships and student financial aid").

These are an organisation's data. The existing rule stands: a register's e-mail address is never stored.
- **A small foundation's address and phone can be a person's.** Charity and foundation registers (the UK Charity Commission, the US Business Master File) often list a trustee's home address or mobile number for small trusts. So these two columns are used **only for P3 matching** (§4). They are never shown to a student and never sent to a model. They are stored in the normalised form P3 compares: E.164 for phones, postcode plus house number for addresses.
- They are refreshed or removed whenever the register row changes, so a row the register drops leaves nothing behind.

**"Top universities only"** (Vietnam, Africa, South America, Mexico; §0.4) uses **TOP-U v1** (owner, 2026-10-03; evidence `.context/research/2026-10-03-top-universities-definition.md`). Its steps, in order:
1. Recognition under §4.1 is the floor (WHED, a state list or a recognised parent): an institution not recognised is never "top".
2. CWTS Leiden Ranking Open Edition membership: at least 1,500 OpenAlex publications in 2020–2023, CC0 data.
3. Corroboration by at least one ranking built on a different database: URAP, SCImago, U.S. News or CWUR. Institutions that SCImago flags as integrity risks are dropped.
4. Survivors are ranked by their share of top-10% papers, keeping at most 25 per country.
5. Where fewer than 5 survive, the list is filled up to 5 from OpenAlex output.

QS and THE are tie-breaks only: their methodologies rest on reputation surveys and on data the institutions submit themselves.
- The research's per-country yield is about 257 institutions across 14 countries. It is an OpenAlex approximation of Leiden's list, not that list. Plan 5 re-derives the counts from Leiden's own data and the national registers. It also guards against OpenAlex affiliation errors (a Mexican college credited with 8,529 works; an Argentine observatory duplicating CONICET), which step 3 exists to catch.

**Where the home-side list comes from.** "Small closed set" means a seeded `ClosedList` with a source URL per row, the same shape as `seeds.py`. It is built once from Azerbaijan's state programme pages, the destination embassies' scholarship pages and a search sweep. Every website on it still needs a proof (§4). "No human" (§0.1) governs runtime decisions; a seed list is a list, like every other register here.

**An eligibility pre-filter runs on the register's own text, before any paid step.** Jev reads the name, purpose and category. There is no page fetch; it costs a fraction of a cent per thousand rows.
- Noul: "Does this body give money to individual students for higher education?"
- Noul: "Does this text state that it funds only citizens or residents of its own country or region?"
- Where a register carries a category code, code decides instead.
- Outcomes are `candidate`, `excluded` or `unknown`. **`unknown` stays a candidate**, because losing a real funder is worse than checking one more.
- This is filter F1. Its bars and fail-open rules are §5.4's, rules 1, 5, 6 and 7, and it is measured there.

**Funders on the home side are a small closed set.** For Azerbaijani students:
- Azerbaijan's state study-abroad programmes;
- diaspora and affinity funders;
- each destination's bilateral or embassy scheme for Azerbaijan.

**Azerbaijan-specific official lists, all included** (owner, 2026-10-03; evidence `.context/research/2026-10-03-funding-source-breadth.md`):
- **`htp.edu.az`**, the Ministry of Science and Education's site for government-to-government scholarships open to Azerbaijani citizens. It covers about 10 destinations (Hungary, Morocco, China, Kazakhstan, Romania, Latvia, Tajikistan, Kyrgyzstan, a Turkish doctoral route, Uzbekistan, MGIMO), and it reposts the GKS and MEXT calls. Plain HTML.
- **The State Programme's yearly list** of programmes it funds: 4,405 programmes at 221 institutions in 32 countries for 2025-26, and 500 places. It says directly what Azerbaijan will pay for.
- **Named national schemes confirmed open to Azerbaijani citizens:** Stipendium Hungaricum (Azerbaijan is a sending partner), the Swedish Institute's SISGP, Chevening Azerbaijan, and Fulbright through the US Embassy in Baku. The breadth note's Chevening and Fulbright citations did not re-verify on 2026-10-03 (timeout, 403), so plan 5 re-reads them.
- **Destination embassies in Baku.** Not yet researched; a research pass comes before plan 5.
- **Dead ends recorded, so they are not re-proposed:** EduCanada (Azerbaijan is not eligible); OAS (Americas only); the Organization of Turkic States' Orhun programme (semester exchange, not degree funding); the Heydar Aliyev grant (funds foreigners studying in Azerbaijan); SOCAR's study-abroad programme (employees only; unverified).

These lists, together with the big national schemes (DAAD, GKS, MEXT, CSC, Türkiye Bursları and those above), make up the **pre-built core** (§0.15). It is verified before launch, so the first Azerbaijani students do not wait.

### 3.1 Government funders at every level (folded in 2026-10-03)

The government-funding design (`2026-09-27-government-funding-discovery-design.md` and its plan 1, branch `claude/gov-funding-discovery-design`, unmerged and never reviewed by the owner) is **folded in here** (owner, 2026-10-03). Its plan 1 is retired. What follows keeps its routes and changes what today's decisions change: verified-only, no human, the funding reader of §5, and the Facebook rule.

**Goal, kept:** find all master's funding from governments, with **MyStart** (Azerbaijan's Ministry of Culture, held on none of our lists) as the bar. Every route aimed at education bodies misses a culture ministry, so the body list spans every sector.

**What counts, kept:** money that can fund a master's degree, meaning scholarships, grants, stipends, support programmes and tuition waivers. **No loans:** the reader's `LOAN` rows are not written. Bonded and forgivable money (YLSY's service obligation) counts and is shown with its obligation stated. That reading is still owed an owner confirmation (§12).

**The body list.** `Organisation` rows for every government body that could fund master's study.
- **Home side (AZ; TR when Turkish students come):** ministries of every sector, their agencies and state funds, state companies, the central bank, provinces and cities. Cities start with the ten largest per country; the rest wait on that sample's yield.
- **Destination side:** each destination's scholarship agencies, and its embassies in Baku.
- **Sources, in order of trust:** official government directories (through the vendors), the agency list, and Wikidata enumeration rows (class × country × `P856`, each with a measured count bound).
- **One list of government domains:** `domains.VERIFIED_SECOND_LEVEL` and `recognition.GOVERNMENT_ZONES` (now on master through PR #158) merge, with one citation per zone.
- **Bodies without their own domain** (embassies on `baku.diplo.de`, a path of `gov.uk`) are identified by domain plus path prefix. This is the shared-host rule of §4.
- **Renamed or merged bodies** keep one `Organisation` with several domains. Wikidata's "replaced by" (P1366) or a directory change triggers it. A body with no website at all is out of scope.

**Routes, all run, measured, and scaled by what they find:**
1. **Each body's own site:** map it, keep pages whose address or title carries a funding word in the page's language (the per-language table of §5 step 1, sourced from Wikidata labels of scholarship Q188823, grant and tuition-waiver items, plus terms seen on real pages), and read them with the funding reader (§5).
   - A site that does not answer stays `NOT_YET_CHECKED`, never "no schemes".
   - **Agency hosts that are also catalogues** (`daad.de`, `campusfrance.org` in `domains._ROUTING`) are citable for the host's *own* schemes when the host is on the reviewed agency list; their programme listings stay routing-only.
2. **Gazettes:** Resmî Gazete, and Azerbaijan's legal database e-qanun.az (rendering vendor rung). Read weekly, on the platform budget. A decree that *creates* a scheme becomes a pointer to its funder. A decree that *amends* one triggers a re-check through §5.5's freshness path; it never edits a row itself.
3. **The receiving side:** destination universities' funding pages that name outside funders ("State Programme students") and the official "study in" portals. Their pointer names feed route 6.
4. **Wikidata scheme entries** (Q188823 with a sponsor), destination side only; AZ and TR have none.
5. **News and aggregators,** read for pointer names only, never cited.
6. **Pointers become leads.** Every pointer name from any route goes name → `resolver.Resolver` → a `ResearchLead` with `found_via=POINTER:<host>`, keeping the pointer's quote. **No human:** a name with no proven site is not a `SITE_UNKNOWN` question for a person; it stays an unproven lead, counted per route, and is retried only when a later route produces the same name.

**Social accounts** (the government design's §5, under today's rules):
- **Which accounts:** an account counts only when the body's own **proven** website links to that exact account (§4's Facebook rule, extended to Instagram and Telegram). Wikidata (`P2013`, `P2003`, `P3789`) may *propose* an account. An account Wikidata alone vouches for is not read, rather than becoming a question for a person.
- **Transport:** Facebook and Instagram through the Browser Use service; Telegram through `t.me/s/<channel>` on the vendor ladder. Poster images are OCR'd at read time through Firecrawl, because platform image URLs expire.
- **What is read:** feed posts only, never stories, reels, groups, private profiles or comments. The first read covers 12 months, then new posts only. A repost is a pointer to its source body, and an image-only post is read through its image text.
- **Source rule:** an official page for the scheme, when one exists, is always the cited source. A post is cited only when none exists. Either way **it is shown only when verified** (§5.5), so the old "being confirmed" card state is dropped.
- **Deleted posts:** only a positive "gone" signal (the service's not-found answer, HTTP 404 or 410) marks a post deleted. A login wall, an empty page or an error is `unreadable` and keeps the previous state. Re-checks follow §5.5's freshness rule.
- **Kept:** post link, date, text, image text and the body. **Never kept:** commenters, reactions, followers or anyone's profile.
- **Tables:** `SocialAccount` and `SocialPost`, shared catalogue: `shared_catalog_select`, `runtime_engine_write`, RLS in the same migration, and a write-denial test through `runtime_connection`.

**The same scheme found in several places.** Rows stay rows; a reversible `SchemeLink` (shared catalogue table) says that two rows are one scheme.
- **Linked automatically** when both rows name the same funder `Organisation` and point at the same official URL, or name the same funder with the same verified deadline and amount.
- **Anything fuzzier stays unlinked**, rather than becoming a `SAME_SCHEME` question for a person. An unlinked near-duplicate is shown as two cards. That is the cost of no human, and the count of same-funder pairs left unlinked is reported.
- **Payer and administrator:** a scheme paid by one body and run by another keeps the payer as holder and records the administrator as a second `Organisation`.

**Target level and special groups.**
- **Target level:** the reader gains a per-track `target_level` question (`MASTER`, `BACHELOR`, `PHD`, `ANY`; §5.2). A scheme with no `MASTER` or `ANY` track is not written. The State Programme is three tracks, and only the master's track's conditions reach a master's applicant.
- **Special groups:** martyrs' families, veterans' families, civil servants, a profession, a named region. These are fixed facts the profile does not hold, so the student answers once on the scheme's card ("Does this apply to you?": Yes / No / Not sure), with the funder's own sentence shown.
  - **Yes** treats the condition as met.
  - **No** hides the scheme and every scheme carrying the same group label.
  - **Not sure** or no answer hides it under verified-only.
  - Answers go to `EligibilityAnswer`, a tenant table in the erasure field set, never sent to a provider or put in a query.
- **Special-category conditions** (disability, religion, refugee status, health) never reach the card. Before today they became a consultant task. Under no-human they hide the scheme. Whether to keep that is an owner question (§12).

**Measured on an answer key.** About 30 government schemes open to Azerbaijani master's students, MyStart first, kept in `docs/research/government-funding-answer-key.csv`. Every row is found independently of the routes and fetched live. This is Part A's **recall** yardstick, reported per route: found, found beyond the key, and cost per scheme found. It is distinct from the owner's gold set, which certifies precision (§5.5), and it never limits what is shown.

### 3.2 Erasmus Mundus joint masters as programmes (owner, 2026-10-04)

**The defect this closes.** `manage.py enumerate_eacea` (`apps/research/eacea.py`) writes each EACEA project as a `RegisterEntry` whose `name` is the project title, bound to the coordinating university. So `recognition.body_names()` counts "EMJM Smart Cities" as one of the coordinator's names, and a consortium site titled with the project name verifies as the coordinator's own website (final review of PR #173). From now on a project title is never a university's name: `body_names()` reads only rows from REGISTER and CURATED_LIST sources.

**Each live EMJM becomes one `funding.Program` with `provision_type=JOINT`.** The schema already has the shape: `Program.awarding_institutions`, and the `JOINT` check that a joint row carries no single `institution`.
- **The list comes from the EACEA project API.** Both action codes, `43690363` (2021–2027) and `31046261` (2014–2020), are queried. That gives 415 projects, with partner organisations, EU-PIC, country and website (CLAUDE.md, "Every EMJM").
- **The programme is read from the consortium's own site** with the same reader as every programme page (Part C). It captures:
  - **intake:** a current or next intake stated on the site. Without one, the EMJM is not written. Ended consortia stay out; old ones still recruiting are kept;
  - **tracks:** one row per track, carrying three things:
    - its **mobility path**: an ordered list of (semester or year, university, country);
    - its **specialisation** name, if any;
    - its **degree awarded**: joint, double or multiple, and from which universities;
  - **requirements and funding**, exactly as for any programme. The EU scholarship is a funding row like any other.
- **Partner universities are bound by EU-PIC** through the existing `eacea.bind_partner`, and each must itself be recognised under §4.1 for the programme to be shown.
- **The consortium site's proof:** EACEA's own catalogue entry for the project links to it, or a proven partner university's site links to it. A consortium domain is a programme's site, never an organisation's.
- **Without the EU scholarship:** an EMJM whose site states no EU scholarship (typically an older consortium still recruiting) is shown only to a student who has said they can fund themselves (§0.21).
- **Matching** (§0.22): a student who names a country is asked once whether an EMJM that studies there for part of the time is acceptable. On yes, an EMJM matches when that country is on any track's mobility path. The card shows each track's full path and which universities award the degree.
- **Not decided here:** the student-profile field for "can fund myself" and for the EMJM answer. They are the tailored-programme build's (`DestinationPolicy`), and plan 7 reads them, never redefines them.

### 3.3 A programme the student types in (owner, 2026-10-04; narrowed 2026-10-05)

**Today** `funding/services.py::consider_named_program` creates a CHECKING candidate and a `ConsultantResearchTask`, and a counsellor must find the official URL and tick "eligible" by hand (`resolve_named_program`). That is a human step §0.1 does not allow, and it is retired.

**From now on (owner decisions, 2026-10-05):**
1. **The student gives the name, and the link if they have it.**
2. **No link: the agent searches for the programme** by name with the existing search providers, and keeps only pages on the site of a body that passes Part B. It shows the student the page it found, with its link, and asks: "Is this the programme you meant?"
   - Yes: the page goes on as if the student had given that link.
   - No, or nothing was found: the student is asked for the link.
3. **Every link, given or found, goes through the existing check** (`provenance_job.check_named_url`): the mill list, registers, curated lists, government zones, homepage identity and RDAP, the same as every catalogue programme.
   - Blocked: "Cannot be added: <reason>".
   - Not confirmed: "Cannot be added: we could not confirm this link is on the university's own website." This is the student's own request, so they are told; §0.18 still keeps every other unconfirmed body out of sight.
4. **Eligibility is eligible or not, never "possibly".** The page is read by the card reader (Part C) and judged like any catalogue programme. Until that has happened the programme shows only "Still being checked." **This flow is therefore built after plan 3** (the card reader), not before it. It is one of the reads a student waits on, so it runs synchronously at standard price and must finish in under 30 s (§5).
5. **Cap: 20 typed programmes per student per paid admissions cycle.** A search or a check counts once, at confirmation; a programme the student withdraws does not give the slot back. The cap is the same for an agency's students, whose agency pays for them (B2B). No "paid cycle" exists in the schema yet (only `reports.ConsultationPayment`), so the cap counts `StudentDecision(CONSIDERED)` rows on the student's runs for the admissions cycle their profile targets, until billing defines the cycle.
6. **What this retires:** the `ConsultantResearchTask` for named programmes, the `research.pending.internal` placeholder, `resolve_named_program` and its counsellor view. It also closes the PR #173 gap: an item still being checked says so.

### 3.4 Application routes (owner, 2026-10-08)

**What it answers:** for a catalogue programme, how a student actually applies. That means which route applies to them, the portals in order, the dates, and the fee. It is extracted and certified on this engine like eligibility and award facts (§5, §5.5). It is not a second reader, and a counsellor's entry is never its primary source. The consumer side is the student dashboard's (elmify-15: lanes, money). Reference-letter slots belong to the requirement reader (elmify-f3), not here.

**Source: the application page, found by code.**
- **The link.** From a proven programme page (Part B), code follows **one hop** of links whose anchor text or URL matches the apply vocabulary.
  - The vocabulary lives in `docs/research/apply-vocabulary.csv` (`locale,term`, in the `locale_names` style): apply, how to apply, application, Bewerbung, ansökan, hakeminen, aanmelden, candidature, iscrizione, 지원, 応募 and so on.
  - No model chooses this link.
- **The page** is kept as an `OfficialSource` of the new type `APPLICATION`. It is kept only when it is:
  - on the proven site; or
  - on an `ApplicationSystem` host (below) reached by a link from the proven page. On a `SHARED` host, the exact tenant subdomain or path linked from the proven page is the proof, never the host itself.
- **Never behind a login.** A page whose readable body is a sign-in form is recorded as `login_wall` and not read.
- **No separate page.** When there is none, the programme page itself is read for routes.

**Facts.** Each is a typed decision with a byte-exact quote (§5: a proposer may only point), read by the §5 reader stack under the §5.5 rule, and gold-certified. It is `UNMEASURED` until its category is certified, and an unmeasured fact is never served. The fixed field names are:

| model | field | values |
|---|---|---|
| `funding.ApplicationRoute` | `program` → `Program`; `track` → `ProgramTrack`, nullable, added with §3.2 | |
| | `intake` | label as the page states it, plus `intake_start` date when code parses one |
| | `audience` | `ALL`, `EU`, `NON_EU`, `NAMED_COUNTRIES` (+ `audience_countries`, ISO-3166 alpha-2 list) |
| | `kind` | `SELF_FUNDED`, `COMBINED_WITH_AWARD` (+ `award` → `FundingOpportunity`, required for COMBINED) |
| | `round_label` | free text from the page, e.g. "Round 1" |
| | `source` → `OfficialSource`, `status` | `UNMEASURED`, `SERVED`, `RECHECK` |
| `funding.RouteStep` | `route`, `position` | ordered from 1 |
| | `purpose` | `APPLY`, `PRE_CHECK` (e.g. uni-assist VPD), `RANKING_ROUND`, `VISA_PREENROL` |
| | `channel` | `PORTAL`, `EMAIL`, `POST`, `NONE` |
| | `portal_url` + `portal_system` → `ApplicationSystem`, nullable | code finds the link candidates; the model only picks among them; the proof rule above applies |
| | `fee_amount`, `fee_currency`, `fee_deadline` | parsed by code from the picked quote; `pays=application_fee` and `date_role=fee_deadline` (§5.2) |
| `funding.RouteDate` | `step`, `role` | `PRIORITY`, `FUNDING_CONSIDERATION`, `FINAL`, `ROLLING`, `DECENTRALISED` |
| | `date` | null for `ROLLING` and `DECENTRALISED`; plus `quote` |
| | `timezone`, `timezone_source` | IANA name. `STATED`: the zone the page states, quoted. `DERIVED`: the institution's local zone, from its city when its country has more than one zone. Empty when neither is known; the student side then counts the deadline as ending at the earliest instant among the country's zones, the safe side for "last safe day" (`portals.Application.deadline_timezone` already carries the result) |

The names avoid `portals.ApplicationStep`, which is the execution trail. Every row carries the per-value reader record (§11.1).

**Certification bounds.**
- Every route field: at most 1 in 100, like every shown field (§0.13).

**Registry: `research.ApplicationSystem`** (platform-shared, curated, seeded from `docs/research/application-systems.csv`). The seed is drafted by elmify-15 from its `.context/research/2026-10-06-application-portals-*` notes and reviewed by the owner.
- **Columns:**
  - `slug`, `name`, `kind` (`NATIONAL`, `VENDOR`), `purpose` (`DEGREE`, `SCHOLARSHIP`), `host_scope` (`SHARED`, `PER_UNIVERSITY`), `hosts` (registrable domains), `country_code` (the country of the body that runs the system; for a `SCHOLARSHIP` system that is the funder's country), `open_publishing` (true when anyone can publish a form on the host, e.g. JotForm, Formdesk);
  - round rules: `choice_limit`, `ranked`, `one_fee_per_round` (e.g. universityadmissions.se: 4 ranked choices, one fee);
  - `prep_lead_days` (e.g. uni-assist VPD), `source_url`.
- **Never filled by a model.**
- **`hosts` rules** (from the 2026-10-09 verification pass, elmify-15):
  - `hosts` lists the login and applicant-portal hosts too (e.g. `dosv.hochschulstart.de`, `accounts.ucas.com`), because a step's `portal_url` often lands there.
  - A wildcard may only stand for the leftmost label under a vendor-owned registrable domain (`*.dreamapply.com`). It never stands for a TLD or a public suffix: `ecandidat.*.fr` would match any `.fr` look-alike, so such a system lists its loaded hosts one by one.
  - A system whose tenants live on the university's own domain (Slate: `apply.iie.org`, a CNAME to `technolutions.net`) has empty `hosts`. It is recognised through the "on the proven site" branch. No CNAME lookup is ever used.
- **Membership never proves a tenant.** Matching a registry host, or a host that resolves in DNS, never substitutes for the exact tenant subdomain or path being linked from the proven page. Vendors such as DreamApply, Tchooz, Osiris and Liaison answer DNS for any name. An `open_publishing` system (JotForm, Formdesk: anyone can publish a form) is served only on the exact form the proven page links. A login host shared by every tenant of a vendor (`id.dreamapply.com`) identifies no tenant, so it is not listed in any university's row.
- **TLS is never relaxed.** A portal with a broken certificate chain (Pastel / Études en France, 2026-10-09) is recorded as such. Certificate checks are never disabled to read it.
- **One registry, both sides.** A `SCHOLARSHIP` system (GKS, CSC, Stipendium Hungaricum, Türkiye Bursları, DAAD, SI, Chevening, Fulbright in the 2026-10-08 draft) is the portal of an award's own application. It is reached through `RouteStep.portal_system` when a route's award is applied for separately (`route_order`, §5.2). A `DEGREE` system is the admission portal.

**Cycle.**
- Routes are per intake. When an intake's `FINAL` date has passed, its routes go to `RECHECK`: never silently reused, and never served.
- An unchanged page costs no model call (`content_sha256`). It is still `RECHECK` when its dates are past, until the page changes or a person confirms the next intake.

**Serving.**
- Only `SERVED` routes reach a student.
- `portals.Application` copies the route at add time (`route_snapshot`: steps, dates, fees, portal URLs, each with its quote and source URL; the tenant-copy pattern). It never reads the catalogue route again.
- Until a programme has a served route, the card shows "Open programme page" (the proven page). The tenant-scoped counsellor portal task stays as a fallback only.

### 3.5 Document file rules: what each file must be called (owner, 2026-10-10)

**What it answers:** the naming rules a programme sets for the files a student uploads: "name your CV Name_Surname_CV", "Lastname_Firstname_Transcript.pdf", "save the file as SURNAME_CV.pdf".

**Who owns what:**
- This is a question set on the engine, read from the programme page and its application page (§3.4's source), never a second reader.
- The store and its consumer belong to the co-pilot document-prep plan (plan 4, `claude/copilot-document-prep`): `Program.file_rules`, consumed by `apps/portals/prepare.py::file_name`.
- Until this set is certified, the grammar reader's `grammar_values.name_options` / `name_pattern` stays as the fallback.

**The record is plan 4's, unchanged:** `{"document", "field", "value", "conditional", "condition", "rule_text", "source_url"}`.
- `document` is one of `CV`, `MOTIVATION_LETTER`, `REFERENCE_LETTER`, `TRANSCRIPT`, `DIPLOMA`, `PASSPORT`, `LANGUAGE_CERTIFICATE`, `EVERY_DOCUMENT`.
- `field` is one of `format`, `combine`, `max_bytes`, `name_pattern`.
- A `name_pattern` value uses only the closed placeholders `{surname}`, `{given_name}` and `{full_name}`; every other character is literal ("Name_Surname_CV" → `{given_name}_{surname}_CV`).

**Candidates, by code:**
- **File-name tokens,** with or without an extension: a run of words joined by `_`, `-` or CamelCase that contains at least one placeholder word.
- **Naming lines:** a line carrying a naming cue ("name your file", "file name", "save as", "dosya adı", "fayl adı", "имя файла", "Dateiname"). Its quote may come from the §5 proposer, kept only when byte-exact.

**Turning a candidate into a pattern, by code only:**
- A per-language placeholder table, `docs/research/file-name-placeholders.csv` (`locale,word,placeholder`), maps the words. Examples: en surname/last name/family name → `{surname}`; first name/given name → `{given_name}`; az ad → `{given_name}`, soyad → `{surname}`; tr ad/soyad; ru имя → `{given_name}`, фамилия → `{surname}`; de Vorname/Nachname.
- **"Name" beside "Surname" is the given name;** "Name" alone is `{full_name}`. This is a code rule, not a model's choice.
- **Prose** ("your first and last name followed by _CV") is parsed only by the same table plus a short list of joining phrases ("followed by", "then", "and"). Prose code cannot turn into a pattern goes to the §5.5 hold queue, where the operator adds the missing word or phrase, never the value.
- **A placeholder outside the closed set** (a patronymic, "ata adı", "отчество"; a date of birth) is not stored and goes to the hold queue, since plan 4 cannot fill it.

**Questions (asked of the §5 readers, under the §5.5 serve rule):**
- `name_rule_document`: a Choice over the `document` values, asking which file the rule names. "All documents" is `EVERY_DOCUMENT`.
- `name_rule_conditional`: a Noul asking whether the rule applies only in some case ("if you upload a combined PDF"). The condition goes into `condition` as the page's quote.

**Bound and serving:**
- 1% per field, like every shown field (§0.13). The value is code-parsed, so the bound measures the document assignment and the condition.
- Until the set is certified, prepared files keep plan 4's default name and the grammar reader's fallback applies.

## 4. Part B — proving a website

**This builds on the provenance gate, which already exists** (PR #158, `apps/research/provenance.py`), and does not duplicate it. `decide()` already proves a domain by `Reason.REGISTER`, `CURATED_LIST`, `FUNDER_LIST`, `GOVERNMENT_ZONE` and `VOUCHED_BY_LINK`. It already catches lapsed domains through RDAP (`_taken_over`: a domain registered after the register first listed it). The show rule already reads `provenance_of_award`. **What this part adds to `decide()`:**
- **P3**, the register's own details on the site (below), as a new proving `Reason`;
- the site-identity condition on `GOVERNMENT_ZONE` (P2 below), if the gate does not already require it. Plan 4 checks this first;
- proof by host and path for shared government hosts, and the Facebook rule (Guards, below).

The table below states each proof's *conditions*. P1 and P2 map onto existing reasons.

**Three proofs, cheapest first, stopping at the first that passes:**

| proof | what it takes | cost |
|---|---|---|
| **P1** | The register lists this website. The site still loads, its final URL stays on the listed registrable domain (`tldextract`), it is not on `AGGREGATOR_DOMAINS`, and the homepage names the organisation. | Free |
| **P2** | A protected address (`domains.verified_kind`: `.gov.tr`, `.edu.az`, `.ac.uk`…) **and** the site's own identity names this organisation: its homepage `<title>` or `og:site_name` (restored by `_with_head`), not body text. The homepage is the one already fetched while finding it. | Free |
| **P3** | The register's details appear on the site: the **registration number** exactly, or the **address and the telephone together**. Look in the homepage footer first (already fetched), then at most two more pages on the same site (legal notice, contact, about). | 0–2 fetch credits |

**Why P1 and P2 carry their extra conditions:**
- **P1, lapsed domains.** Registers keep websites for years, and an expired domain is bought and parked or turned into a casino. A register-listed address that now redirects elsewhere, or no longer names the organisation, is not proof.
- **P2, regulators' pages.** A protected address that merely *mentions* the organisation proves nothing: YÖK's site (`yok.gov.tr`) names every Turkish university, and a ministry page names every body it funds. Only the site's own name, taken from title or `og:site_name` on its homepage, says whose site it is.

**How code matches** (no model is asked; every match is code):
- **Names:** case- and accent-folded, with legal-form words removed (GmbH, e.V., MMC, ASC, LLC…). Matching tries the register's name in each script it provides, plus a transliteration where the register gives only one script. An exact match after folding passes; anything looser fails, and the organisation moves on to the next proof.
- **Registration numbers:** digits and letters only, separators removed, and matched whole, never as part of a longer number.
- **Telephones:** parsed to E.164 with `phonenumbers` (the maintained Python port of Google's libphonenumber, `github.com/daviddrysdale/python-phonenumbers`, 9.0.40 on PyPI on 2026-10-03). This is a new dependency, added in plan 4; hand-written parsing of 40 countries' formats is exactly what buy-before-build rules out.
- **Addresses:** postcode plus house number, both found on the same page as the phone. A free-text address string is never compared.

**Guards:**
- A name alone never proves anything.
- A page showing registration numbers of several bodies is a directory, and fails P3.
- **Shared government hosts are proven by host and path, not by registrable domain.** `OrganisationDomain.registrable_domain` is unique, but EACEA and the European Commission both live on `europa.eu`, and every UK department and embassy on `www.gov.uk` (measured by the 2026-10-03 audit). For a host on a short list of shared government hosts, the proven unit is host plus path prefix (`www.gov.uk/government/organisations/chevening…`), linked to a parent body. Without this, "neither is saved" would drop both sides of every such pair.
- If one website (or, on a shared host, one host plus path) is proven for two different organisations, **neither is saved**. This replaces the "a person decides" rule for `CONFLICT`.
- **A Facebook page counts only when the body's own proven website links to that exact page** (owner, 2026-10-03; evidence `.context/research/2026-10-03-az-ministry-facebook-proof.md`). Its posts are then read and verified like any page.
  - Every Azerbaijani body checked links its page from its own site: the Ministry of Science and Education, HTP, the NGO Agency, the Youth Foundation, the Ministry of Youth and Sports, ASAN, ADA and the Heydar Aliyev Foundation. gov.az's own domain register names the holder of each `.gov.az` site.
  - Meta's blue badge is ignored. It can be bought, it is missing on HTP's scholarship page, and Meta says posts from verified pages are not themselves verified.
  - The name check still applies: the Hungarian embassy's site links to a different organisation's page.
  - This is how the 2026-09-27 decision to serve Facebook-only schemes survives verified-only (`facebook.com` stays on `AGGREGATOR_DOMAINS` for every other purpose).
- **No URL is ever taken from a request.** A student's need decides *when* proof runs, never *which* site. The candidates come from a register or the resolver. Proven websites and award cards are shared catalogue rows every tenant reads, so a tenant able to steer the URL could put a hostile page in front of every other tenant (the `ProgramStatement` rule in `CLAUDE.md`). Writes go through the catalogue role, not the tenant's.

**A proof can go stale, and it is re-checked only on evidence, never on a schedule:**
- the register row changes;
- a later fetch of the site lands off the proven registrable domain;
- or the homepage, fetched for any reason, no longer names the organisation.

Any of these sets the website back to `NOT_YET_CHECKED`. Its cards stop being shown until the next proof.

**What gets recorded:** each saved website carries its proof kind, the page that showed it, and the matched text.

**When proof runs:** for the pre-built core, before launch (§3); for everything else, the first time an organisation becomes a candidate in a real student's pack.
- An organisation that cannot be proven is marked `CANNOT_PROVE`. It is revisited **only when its register row changes**, never on a schedule.
- A vendor outage leaves it `NOT_YET_CHECKED`, so an outage never writes off a real funder. It is tried again only when a student next needs it.
- Spend stops at the existing per-run and per-month budgets (`FIRECRAWL_MONTHLY_CREDITS`, `SCRAPEDO_MONTHLY_CREDITS`, `DECISIONS_MONTHLY_TOKENS`, `DECISIONS_RUN_TOKENS`).
- **Catalogue work is charged to a platform budget, never to the student** (owner, 2026-10-03). Proof, fetch, reading and verification of an organisation serve every later student and tenant, so they draw on a platform-wide monthly budget: the existing `FIRECRAWL_MONTHLY_CREDITS`, `SCRAPEDO_MONTHLY_CREDITS` and `DECISIONS_*` budgets. `wallet.py`'s per-student cap ($50 per intake, a per-tap share, a tenant ceiling) keeps covering work *about the student*: their search and their letters. **Corrected the same day:** `apps/research/wallet.py` has **no callers** on master (`charge` is never called), so it caps nothing. The per-user and per-tenant brake `CLAUDE.md` requires on a model-calling request path is therefore `rate_limited()`, keyed per student and per tenant, on student-*triggered* catalogue work. The platform still pays for it; the limit only stops one account draining the platform budget. Limits are settings. Pre-built-core and scheduled work are not student-triggered, and do not count against them.
- **One organisation is checked once at a time.** Two students needing the same unchecked organisation must not pay twice. The check is a job row with a uniqueness constraint per organisation, claimed with `SELECT … FOR UPDATE SKIP LOCKED`, and a second request waits on the first's result. This has to work across tasks on separate machines (web and worker run as several ECS tasks on one database), so an in-process lock is not enough.
- **"Checking…" for about a minute** (§0.3) is a wait, not a timeout that loses the work. If the check has not finished, the pack shows what is ready and the job carries on. Its cards appear on the student's next view; nothing is retried on a schedule.

**The resolver keeps one job: proposing up to two candidate websites.**
- Its kind vocabulary is tuned by practice rather than by a fixed rule:
  - practice tries tree depths 2, 3 and 4 on other countries' organisations whose websites Wikidata already records, and keeps the depth that finds the most;
  - it runs only when resolver code or vocabulary changes, capped at about 100 organisations ($1–3).
- The "if depth 3 misses a word, stop" rule is retired. A missing word now costs a little search accuracy, never a wrong saved website, because proof decides what is saved.
- The Vietnamese hold-out becomes practice data.
- `RESOLVER_WRITES_ENABLED` is replaced by "a website is written only with a recorded proof".

### 4.1 Universities in any country: the lean rule (U1, settled 2026-10-03)

The owner chose this after a brainstorm, two research notes (`.context/research/2026-10-03-u1-state-recognition-sources.md`, `…-u1-directory-coverage.md`) and a live test on eight universities. A tiered scoring rule was designed first and dropped as over-engineering for the risk.

**What "proven" guarantees** (owner): the university is real, **recognised by its own country's state**, and the website is its own.

1. **Recognised** when any one of these holds:
   - **WHED** (IAU) lists it. WHED is the only worldwide list whose entry rule is recognition by the national competent body (about 21,500 institutions in 190 countries, with websites).
   - **the country's own official list** lists it (verified so far: UK OfS, AU TEQSA, CN MOE, BR e-MEC, NG NUC, CA CICIC, CH, RU, NZ; the existing GB, KR, DE, TR and AZ registers);
   - **a recognised parent.** An official source (a ministry page, a regulator's list, or the parent's own proven site) states that the institution operates as part of, or on the basis of, a recognised parent. Examples: UFAZ on ASOIU (edu.gov.az's announcement; UFAZ's "Establishment of UFAZ" page links ASOIU, `vouch.py:206`); branch campuses such as Georgetown Qatar and NYU Abu Dhabi. A branch campus also needs the host country's licence list where one exists, such as the UAE's CAA.
2. **Its website** is the URL the recognising source gives. Where it gives none, ROR's or Wikidata's URL is used instead (ROR's `education` type includes schools and institutes, and Wikidata keeps former URLs, so neither proves recognition).
3. **One check, by code:** the homepage, fetched through the vendors, names the university by **any of its known names**: WHED's English and local-language names, Wikidata labels and aliases, and acronyms. The name may appear in the `<title>`, `og:site_name`, the logo's alt text, the header or the footer copyright. **A university is proven once and not re-checked on a schedule** (owner, 2026-10-03, after being told the cost was about 1¢ a university a year). `provenance_job.next_check()` returns no next check for a RECOGNISED university, so `ProvenanceRecheckRule`'s 30-day cycle (`PROVENANCE_CYCLE_DAYS`) no longer applies to universities. What still catches a change, at no extra cost: every programme or funding page fetched from the site runs `require_same_origin`, so a dead or redirected site fails there and sets the university back to `NOT_YET_CHECKED`.
4. **The existing domain-history check (`_taken_over`, RDAP) runs where a registry publishes RDAP,** which is only 18 of 68 destination domains. Nothing new is built for the rest.

**Measured on 2026-10-03:**
- Under this rule all eight test universities pass: UFAZ through ASOIU, UBD, Qatar University, UAE University, King Saud, Nazarbayev, Oxford and MIT.
- Two defects in the earlier design were found and are fixed by steps 2 and 3. A **title-only** identity check failed on Qatar University (its title is Arabic for "Home") and on UFAZ (the title gives only the acronym).
- **Name lookups must match exactly:** a WHED search for "Oxford" listed Oxford Brookes first.
- Oxford's homepage refuses a plain client (403); production fetches go through the vendors.

**Dropped as over-engineering** (owner): strong and moderate signal scoring, uniRank and Webometrics ingestion, a protected-academic-domain table, and a WHOIS fallback for the 50 domains with no RDAP.

**The risks accepted:** with no re-check, a university that loses recognition (WHED delists it) or changes domain stays as first proven until a page fetch from its site fails. And in a country without RDAP, a lapsed domain could still carry the old name. Both are rare for functioning institutions.

**Build:** a WHED reader using one lookup per institution. IAU's consent of 2026-09-11 ("You can scrape and access without any problem") is on file in `docs/superpowers/research/2026-09-11-whed-recon.md`; it does not name storage or commercial use (§12). Also: exact-name matching, the all-names identity check, the parent rule, and national lists only where WHED's coverage of a country is thin.

**`CLAUDE.md` deleted the WHED and DEQAR readers on 2026-09-14** and said registers return only by a product decision. This is that decision, for a narrower purpose than the deleted screen had:
- the owner made state recognition a condition for showing a university (§0.10, this section);
- the platform reads WHED once per institution, which `CLAUDE.md` names as "the cheap shape";
- DEQAR is not revived.

`CLAUDE.md`'s record is updated when the plan lands.

## 5. Part C — the funding reader

**The reader, from slice 2** (owner, 2026-10-08 to 2026-10-12; §0.24–30). It replaces the Jev-only reader recorded below wherever the two differ.
- **The unit is the award, read in context.** The reader reads the award together with its page section: its headings, the lines around it, and its links. A cheap line filter may first choose which lines matter (step 2). It never makes the final decision, and the line-by-line yes/no of round 1 is not the reader.
- **Code finds the candidates, and a model may only point.** The code finders of slice 1 (`apps/research/candidates/`) supply the candidates. A reader may also propose quotes, which code keeps only when they are byte-exact substrings of the page. Code parses every value.
- **The readers:**
  - **DeepSeek V4.1 Flash** (`deepseek/deepseek-v4.1-flash` on OpenRouter, pinned to one stable host) and **GPT-6-luna** (`openai/gpt-6-luna`, sent without `temperature`, which returns 404 on it) read every award.
  - **Both agree:** the answer is accepted.
  - **They disagree** (about 8% of answers): **Claude Opus 5.5** (`claude-opus-5-5`) decides, asked the same question over the same section.
  - **Not in the reader:** Sonnet; Jev and Kimi K3. Jev may come back later as a measured filter (§5.4), never as a reader.
- **The reader list is configuration.** It is one setting that names the models, hosts and the deciding model. Every question set on this engine reads it: funding, application routes (§3.4) and file rules (§3.5). Other sessions reuse it rather than choosing their own. It stays provisional until round 2 (§5.5) confirms it.
- **Measured** on 211 owner-judged hard cards under the 2026-10-11 definitions (v3, §5.2.1); spike at `~/agent-workspace/elmify-runs/slice2-spike/` (`v2/`, `check/strata.md`, `v2/api/costs.md`):

  | reader | precision | recall |
  |---|---|---|
  | DeepSeek + Luna, Opus on a split | 0.980 | 0.925 |
  | Opus alone | 0.980 | 0.932 |
  | Jev + Kimi (the 2026-10-05 rule, old definitions) | — | 0.25 |

  - Adding a third reader, or Sonnet, changed 1–3 cards, which is noise.
  - The errors left are shared by every model: definitions, missing context, and values that sit on another page. Definitions are fixed through the hold queue, context through award-level reading, and other pages through the site hunt (§5.5 steps 4 and 6).
  - Cost per card: DeepSeek $0.000152 and Luna $0.000079, with about 2.4 s per eight-card call, reasoning off.
- **Every reader call follows `CLAUDE.md`'s LLM rules:**
  - the page text is labelled as data, never instructions;
  - the output is schema-constrained (Pydantic, `extra="forbid"`);
  - maximum output tokens are capped;
  - a per-tenant and per-run rate limit goes through `apps/ratelimit.rate_limited()`.
- **Spend and time** (§0.28):
  - **Spend:** at most $0.25 of model spend per page. The measured design costs about $0.01–0.02.
  - **The background catalogue sweep** buys its readings at batch prices (the vendors' Batch APIs, 50% off), and it may take hours per page. The batch transport exists already (`model_cost.ReadingTier`, `batch_reading.py`), and its rules carry over:
    - a request a batch did not finish counts as missing, never as an answer;
    - no transaction is held across a batch.
  - **A page a student waits on** (a typed programme, §3.3, or an on-demand single-page read) runs synchronously at standard price and must finish in under 30 s.
  - **The first job is the catalogue sweep.**
- **One engine, generic from the start** (§5.4): the funding question set comes first, then application routes (§3.4) and document file rules (§3.5).
  - **Slice 2 builds:** the engine, the funding question set, the site hunt (§5.5 step 4), the typed card, the single-page entry and track-shaped output.
  - **Not in slice 2:** storage, wiring the serve rule into `pipeline._fund_page`, and deleting `funding_judge.py`'s vote (all slice 3); the cycle verifier (slice 4).
  - **D8 (step 0) still comes first:** nothing in this reader ships before it.

*Superseded 2026-10-12, kept as the record:* **Jev is the only model in the reader** (owner, 2026-09-27). Code finds candidates, Jev picks among them, code copies the pick. A writing model may only **point** (owner, 2026-10-05: hybrid extraction, replacing "no writing model anywhere on this path").
- **The proposer.** It proposes value quotes per line. It is DeepSeek V4.1 Flash on Fireworks: thinking off, strict JSON schema, eight lines a call. It lands in plan 3 slice 2, beside Call 1; slice 1 stays code-only. *(Slice 2 folds the proposer into the readers above: each reader may propose quotes, and the byte-exact rule below is unchanged.)*
- **Code keeps a quote** only when it is a byte-exact substring of that line, then parses it with the same parsers as the code finders. The stored value is always the page's own text, located and parsed by code. *(Still true.)*
- **Code finds and kept quotes are unioned as candidates.** ~~Jev (with Kimi and the Sonnet tie-break, §5.5) still decides every role. Jev stays the only model that judges.~~ The union stands. Since 2026-10-12 the readers above decide every role.
- **A line with no candidate from either source** is recorded as `no_candidate` with the line, and that count is the metric that improves the finders. *(Still true.)*
- **Measured on the 1,400 keyed round-1 lines** (`docs/superpowers/2026-10-05-hybrid-extraction-measurement.md`, `claude/card-reader-finders` acbea18e):
  - cost $0.08;
  - 765 of 769 quotes byte-exact;
  - lines found, code alone → code plus proposer: requirements 7/50 → 28/50, nationality 51/64 → 60/64, dates 35 → 36, money 21 → 22, levels 147 → 151;
  - the proposer-only finds were hand-checked as real values.
- **Rejected, with the reason recorded in `.context/research/2026-10-05-typed-value-extraction-architecture.md`:** LangExtract (fuzzy 0.75 matching by default), GLiNER/NuExtract, and temporal taggers. No reader is asked to calculate, compare dates, count, or write text. Those were documented as Jev's failure modes (`model-jaggedness/jev-1.13`), and the rule stays for every reader: code does them.

**Steps for one page.** *These steps were written for Jev. Under the slice-2 reader they keep their order, their candidates and their code rules, with three changes:*
- *step 2 (Call 1) is the optional cheap line filter, which only chooses lines;*
- *steps 3 and 5 are asked of the reader pair per award with its section (Opus on a split), not of Jev;*
- *the Jev-only mechanics (the 32,000-token state, `inspect` by name, token-estimate chunking, Choice confidences) apply only where Jev still runs, and otherwise stay as the record.*

0. **Injection screen.** Typed-decisions D8 runs on the page's lines. A quarantined page yields no award. **D8 is specified, not built**: its two Nouls appear in no branch (searched 2026-10-03), so plan 3 builds it, and nothing in this reader ships before it.
1. **Lines.** `funding_judge.funding_lines` already produces numbered lines, each under its heading.
   - The page text it splits comes from `readable_text(..., terms=_FUNDING_TERMS)`, which keeps only sections that match the term list. A section it drops is never read, so **the term list is a fetch filter in all but name** and follows §5.4's rule: it must fail open. It is therefore a per-language data table like the currency forms (§5.3), covering every destination language (ösztöndíj, Stipendium, burs, təqaüd, стипендия, 奨学金, 장학금, 奖学金…), and §7 scores it like F2: funding lines inside dropped sections must be zero on the measurement set.
   - A table row carries its header row as a separate field, so "€1,200" in a row keeps the column that says what it is.
   - A heading is context and an award-name candidate, never a fact line.
   - The page is read in its own language (§5.3). Nothing is translated.
2. **Call 1 — which lines matter.** *(Slice 2: the optional cheap line filter. It follows §5.4's rules, so it fails open and never decides a fact. Its model is chosen by measurement, and Jev is a candidate.)* One call over the whole page, chunked. **The chunk is set by the token estimate, not by a line count** (decision engine §3.2). The whole request, state *and all* questions, is budgeted at 32,000 tokens, because OpenRouter's Jev guide says "Context length is 32,000 tokens" while TypeSafe documents 64k. Measured 2026-10-03: a request carries about 270 tokens of fixed overhead, the state is billed once, and each question adds about 20–46 tokens. So 120 lines × 8 questions (about 960 questions) takes about 24k of the 32k, and a dense page overflows a fixed 120-line chunk. Plan 3 therefore splits Call 1 the way `grammar_questions.pack` already splits the requirement reader, with `_estimate_tokens` over state plus questions. The three speculative questions are asked only on lines a code pass did not already settle: a line with a currency span needs no `has_amount`.
   - Measured 2026-09-27: one compound question with "or" in it flagged 274 lines in one wording and 562 in another. Five one-property questions are what the vendor's rules ask for, and each has a stable meaning to test.
   - The bar is P ≥ 0.35 on any of the five, because a missed award costs more than an extra line read.
   - In the same call, three speculative yes/no questions per line: states an amount; states a date; states who may apply. They cost only their own tokens, and code reads them only for flagged lines, to decide which finders run and to count `no_candidate`.
3. **Call 2 — which award each line belongs to.** *(Slice 2: asked of the reader pair, with Opus on a split.)* One call over the funding lines, the page title, and every heading above a funding line.
   - Per heading, a yes/no: is this the name of one scholarship, grant or award programme? Criteria say that a benefit ("Monthly Stipend", "Accommodation"), a section ("How to apply", "FAQs") or navigation is `false`.
   - Per funding line, a Choice over the headings that passed, plus `page_award` (the page's own title stands for the award) and `not_an_award`.
   - Code: if no heading passes, every funding line belongs to `page_award`; a line assigned `not_an_award` at confidence ≥ 0.6 is dropped, otherwise it stays with the nearest award above it.
   - Measured 2026-09-27: grouping by raw headings made Türkiye Bursları's benefit sections into fourteen awards and "Childpage navigation" into one.
   - This is a separate call because a Choice with many options for every line of a long page exceeds Jev's 32,000-token context (`decisions.MAX_STATE_TOKENS`, OpenRouter's listed `context_length` for `typesafe/jev-1.13`; `ask()` refuses a larger state with `StateTooLarge`). Every chunk size in this section is set against that number, with `_estimate_tokens`'s pessimistic count for non-Latin scripts.
4. **Candidates, by code, per award.** Every value a card will show is found here, so this is where tests concentrate:
   - **Amounts:** every span that pairs a number with a currency form from `docs/research/currency-evidence.csv` (symbols, codes and words in 71 forms already, extended per language); `card_fields._figure` reads the number. An amount in parentheses right after another ("HUF 65,000 (approx. 180 EUR)") is paired with it as a conversion, and the pair is asked about once.
   - **Ranges and approximations are code's** (decision-engine §3.11, measured on session f7's v5 data, `.context/research/2026-10-03-dates-and-bounds-fixes.md`):
     - Amount ranges ("50만원~150만원", "entre 1 200 et 2 100 €", "¥143,000～145,000", "X–Y", до / ile / ilə / arası) are recorded as `range` (min, max), verbatim.
     - Approximations (내외 / 약 / about / approx. / около / yaklaşık / təxminən) are recorded as `approximately`.
     - Date ranges become one candidate with one role question.
     - Year-only and academic-year spans go to the intake finder; with that change the date finder matched 208 of 211 key dates.
     - `dateparser` 1.2.2 was measured and rejected (tr 20/52, ko 4/59, many false hits).
     - The finders are built in the decision-engine session's plan 3.
   - **Relative dates** (owner gold check, 2026-10-05). A number with months, weeks or days, plus before or after, plus an anchor ("start of the grant", "programme start", "academic year"), is a `relative_dates` candidate found by code. Example, Fulbright: "opens approximately 15 months before the anticipated start of the grant; deadline approximately 11 or 12 months before".
     - It is stored as an offset and an anchor, plus `approximately` when hedged, and a range for "11 or 12".
     - `date_role` is asked of it like any date.
     - It becomes a calendar date only when the anchor's date (the intake) is known, and is then shown as approximate.
   - **Dates:** spans with day, month and year parts in the page's language. **Code parses the parts; no reader is asked for a month, day or year that code can read.** Only a numeric date whose order is ambiguous ("10/11/2026") gets a question. A span with no day is a month, never given one: the 2026-09-27 run's every "wrong day" was a finder that clipped "February 2027" to "February 20".
   - **Durations:** a number with months, years or semesters, or "standard period of study".
   - **Intakes:** "2026/27", "2026–2028", "Fall 2026", on the line or its header row.
   - **Places:** country names in the page's language, `funding/regions.py`'s regions, and the Erasmus vocabulary (programme countries, partner countries, EU/EEA, non-EU, developing countries, the DAC list).
     - `regions.py` holds seven regions today (EU, EEA, Western Balkans, Eastern Partnership, ASEAN, African Union, Commonwealth) with English names only. The groups that decide an Azerbaijani student's eligibility are mostly missing: the DAC list, Erasmus partner-country regions, the Organization of Turkic States, the CIS and the OIC. Each is a row with its defining URL, and each name gets its forms in every destination language.
     - `regions.py` says an unknown region is "resolved by a human adding a row". Here an unknown region is `no_candidate`: counted, never guessed, and the count tells us which row to add.
     - **Since 2026-10-12, a group phrase is read through the funder's own list first, and otherwise through the fixed fallback of §5.2.1** (CIS, "developing countries", Global South, low- and middle-income, LDC, Sub-Saharan Africa). The fallback's lists become `regions.py` rows with their source URL and an `as_of` date. A phrase the fallback sends to the hold queue is held, never guessed.
     - `regions.py`'s existing `REGIONS` are kept: EU, EEA, WESTERN_BALKANS, EASTERN_PARTNERSHIP, ASEAN, AFRICAN_UNION and COMMONWEALTH. PR #195 fixed COMMONWEALTH and ASEAN against their own sources. The OIC, the Organization of Turkic States and the Erasmus+ regions are still missing, so a phrase naming them is `no_candidate` as above.
   - **Who may apply:** degree levels, languages with CEFR levels, grades with their scale, ages. Since 2026-10-12 this also covers year-of-study phrases (through the per-country table), required tests and certificates, residence limits, stateless persons and compatriots abroad (§5.2.1).
5. **Call 3 — facts, once per award.** *(Slice 2: asked of the reader pair over the award and its section, with Opus on a split.)* The state is that award's lines (with their header rows) and the candidate maps, every part keyed by name (`amounts.m3`), because Jev addressed by list position answered about a neighbour (measured in the transcript reader). The questions are the catalogue in §5.2. When the token estimate exceeds the limit, the amount questions are split across calls that share the same state.
6. **Code assembles the card.**
   - Identities are enforced in code, never expected of the model: a place both "eligible" and "excluded" at the bar is `not_stated`; a `fee_charged_to_student`, `cost_estimate` or `total_budget_or_count` amount never becomes a benefit; a conversion pair becomes one benefit in two currencies; a past intake is dropped for the student's intake; an impossible date is `not_stated`.
   - A value takes the lowest confidence among the answers it was built from, and below its bar the award climbs the ladder and is hidden until it passes (§5.5), never a guess and never "not stated".
   - The same award across pages is one card: the holder's own page is the source, other pages are pointers.
   - **Scope keeps today's five values** (`funding_judge._Scope`: `PROGRAM`, `PROGRAMS`, `INSTITUTION`, `HOLDER_OWN`, `POINTER`), because the pack needs to know whether an award follows one programme or the whole university. Code derives it: `POINTER` from `apply_elsewhere` (§5.2); on a university's page, `INSTITUTION` when `institution_wide` passes, otherwise `PROGRAM` when the lead is a programme page; `HOLDER_OWN` on a funder's own page. An `INSTITUTION` card is shown only when the page's origin is the institution's proven website (§4), which is the check `CLAUDE.md` says must exist before such rows are served.
7. **When a card is shown.** `FundingOpportunity.served` keeps its name and its readers: `funding/pool.py::candidate_pool` filters on `served=True`, and the database constraint `funding_opportunity_served_not_suspended` stays. What changes is who sets it. The reader sets `served` by the rule below instead of three-reader unanimity, and `manage.py funding_review` no longer reviews values: it comes back only as the hold queue (§5.5 step 6, §0.29). Wiring this rule into `pipeline._fund_page` is slice 3's. A card reaches a student only when all of these hold; otherwise it is stored with `served=False`:
   - the page's website carries a recorded proof (§4) and the page's final URL is on that website's origin;
   - the page was not quarantined (step 0);
   - the award has a name at its bar, `discontinued` is below its bar (`window_closed` never hides a card; it adds a note with the next opening when a date is found), and at least one benefit (an amount, a waiver level or an in-kind extra) passed its bar;
   - **every value the card shows is verified** (§5.5), and the student is eligible on verified facts (§5.5).
   - **A value is shown, verified, or the award is hidden.** There is no "not stated" for a value the engine was unsure about, because that would assert something false about the page. A field is left off the card only when code finds **no candidate at all** for it on the award's lines: code-certain absence, not model doubt. When candidates exist and the decision is unsure, the whole award is hidden and goes up the ladder (§5.5).

**Freshness and recurring awards** are part of verification: §5.5.

**Cost:** about **1–2 cents a page** with the slice-2 readers (§5, above), capped at $0.25 and halved for the batch-priced sweep, against $0.35 today. *(Record: the Jev-only design was costed at about 0.25 cents a page for the three calls, measured at 0.11 cents with fewer questions.)*

### 5.1 Rules for every question

From the vendor's documentation (`research/2026-09-23-jev-question-engineering.md`), in the order they bit during the measurement. *Written for Jev. Since 2026-10-12 they bind the question text every reader gets (one property, literal wording, "yes" means present, a `not_stated` option, English questions, code does the counting). The Jev-only mechanics (`inspect` by name, Choice against Noul confidences, one call per state) apply only where Jev still runs.*

- **One property per question.** No "or" inside a question; combine in code.
- **Literal wording.** Jev answers the question written, not the one meant. "Is it offered or open" was answered no on pages that never say "open". Ask about what a page literally states.
- **Point at the part by name:** `inspect: "`amounts.m3`"`, on a state keyed by name, never indexed.
- **A yes/no is phrased so that "yes" means the thing is present.** Criteria (`true` / `false`) are added only where the measurement shows unclear answers.
- **A Choice is relative and a yes/no is absolute.** Which one of these → Choice. Is this so → yes/no, which can be low for all. Never both for the same fact, and never a bar carried from one to the other.
- **Every Choice has `not_stated` or `none`.**
- **Options are short snake_case words the model reads;** only confusable options get a `{what, not_for, examples}` description.
- **All questions about one state go in one call.** The state is billed once; a speculative question costs only its own tokens.
- **Question text stays English on every page.** The page's language is a field in the state (`page.lang`), and a `note` field ("The lines are in Turkish.") is a measured variant, not a default.
- **Code counts, code computes, code parses.** A reader decides only what needs a judgment.

### 5.2 The question catalogue, version 1

Every question ships in two wordings (A and B) for §7's wording test; the winner is written into `decisions.py`, the loser kept beside it with its score. Bars are the starting values; §7 re-sets them per language.

**Call 1 — per line** (`inspect` the line):

| id | wording A | wording B | bar |
|---|---|---|---|
| receives | Does this line say that a student receives money, such as a stipend, grant or allowance? | Does this line say students are paid or given money? | 0.35 |
| waived | Does this line state that a fee is waived, reduced or not charged for a student? | Does this line say a tuition or other fee is reduced or free? | 0.35 |
| position | Does this line state a paid position for a student, such as an assistantship, internship or research post? | Does this line offer students paid work as part of the programme? | 0.35 |
| in_kind | Does this line state support in kind for a student, such as housing, insurance, travel or a language course? | Does this line say students get accommodation, insurance, travel or courses provided? | 0.35 |
| none_available | Does this line state that no scholarship, funding or financial support is available? `true`: no funding exists for anyone on this programme or page. `false`: it excludes only some group, level or year (that is `excluded_*` or `requires_*`). | Does this line say there is no funding? | 0.35 |
| has_amount | Does this line state a sum of money? | — | speculative |
| has_date | Does this line state a calendar date or a deadline? | — | speculative |
| has_eligibility | Does this line state who may or may not apply? | — | speculative |

**Call 2 — per heading and per funding line:**

| id | wording A | form | bar |
|---|---|---|---|
| is_award_name | Is this heading the name of one scholarship, grant or award programme? `true`: a named award or scheme. `false`: a benefit it includes, a section such as "How to apply" or "FAQ", or navigation. | Noul | 0.60 |
| award_of_line | Which award do the statements in this line belong to? | Choice over passed headings + `page_award` + `not_an_award` | 0.60, else nearest award above |

*Amended 2026-10-05 from the owner's gold check of engine-eval round 1 (elmify-82; `docs/superpowers/2026-10-04-engine-eval-round-1.md`, commit 519e9f48 on `claude/engine-eval-round-1`).
- **Result:** 114 facts checked, 109 right (deadline 14/14, eligibility 66/70, money 29/30). All 5 errors were question definitions.
- **Changes:**
  - relative dates as code candidates (§5 step 4);
  - `amount_for_level` for a line naming two levels;
  - `postdoc` in `target_level`;
  - current study is a requirement, not the level offered *(superseded 2026-10-12 by definitions v3 for year-of-study wording, which now names the level through the per-country table; a completed prerequisite degree stays a requirement, §5.2.1)*;
  - negated coverage is `none`, never a waiver;
  - `eligibility_elsewhere`, so a pointer to a country list is followed, never read as open;
  - for the portal and funding-route catalogue (elmify-15, 2026-10-08): `date_role=fee_deadline`, `pays=application_fee` (a fee charged for applying, never confused with tuition), `route_order` and `renewal_condition`. That catalogue's programme-page facts (how-to-apply URL, portal chain, reference-letter mode) are its own question set on this engine, never a second reader;
  - `amount_for_X` (owner, from the check page): an amount for a spouse, children or dependants is never added to the student's own benefit total. The card shows it as a separate conditional row, "If your family comes with you: +X per month (condition)". `extra_*` gains `family_support` for awards that state family support without a sum. If the student profile records dependants (a tailored-programme profile field, not defined here), the row is highlighted; otherwise it is always shown as conditional.*

*Amended 2026-10-05 with the card-fact definitions v2, validated against the owner's own marks (36 facts; `/home/orkhan/agent-workspace/elmify-jev-harness/question-definitions-v2.md`, relayed by elmify-75). Jev alone, on the same state, went from 13/36 with the earlier questions to 27/36: covers_living 4→10/10, duration 0→7/9, frequency 4→5/6, bound 3/7, eligible 2/4.
- `covers_X` counts only a named purpose.
- `period` is split into `frequency` and `duration`.
- `bound` gains `approximately`, with ranges detected in code.
- `eligible_pN` includes students of an institution named after the place.

Owner decision 2026-10-05 (morning): no paid second reader until one is certified on the owner's gold set from Jev's unsure band. **Superseded the same day for the serve path; see §5.5, "Serve rule until certification".***

*Amended again 2026-10-03 from session f7's v5 measurement (48 pages, 9 languages), relayed by the decision-engine session:*
- `date_role` gains `selection_or_award` and `funding_period`: most of the key's `other` was Korean 선발시기 selection months. `date_role` was precise at its bar (8/8) but covered only 15%.
- `bound`'s confused labels get criteria.
- **Order-swapped pairs bought about nothing** (forward ≈ agree ≈ average for `pays`, `bound` and `period`), so they are a **measured arm, not the default**. "Order-swapped pair" in the table below means "asked as a pair when the harness shows it helps for that question and language".
- **Eligibility place candidates come from every line in a section that holds a funding line**, not only from the money line: eligible 103/123 after that change.

*Amended 2026-10-03 from the decision engine's audit (§3.8, commit 74903833), with probe evidence in `.context/research/2026-10-03-engine-probes.md`. **Order-swapped pair** (engine §3.6): the Choice is asked twice in the same request with the options reversed; it stands only when both orders agree, at the lower of the two confidences.*

**Call 3 — per award** (`inspect` the candidate; "these lines" means the award's lines):

| id | wording A | options | bar |
|---|---|---|---|
| pays | A: Who pays the amount in `amounts.mN`? B: What is the amount in `amounts.mN`, read on its line? | `paid_to_student`, `fee_charged_to_student`, `application_fee`, `fee_reduction`, `in_kind_value`, `cost_estimate`, `total_budget_or_count`, `other`, `not_stated`; order-swapped pair. Criteria: a sentence saying a cost is NOT paid by the programme is never `fee_reduction` | 0.85 |
| covers_X | Does the text state that the amount in `amounts.mN` is for X? One Noul per item X: tuition, living (subsistence, food or day-to-day expenses), travel, housing, insurance, relocation; `total` when the line states it covers everything. `true`: the text names X as what this amount pays for. `false`: a scholarship, stipend or allowance whose purpose is not named, or an amount named for other costs. Owner: "100 manat per month as a scholarship" is NOT living costs. An amount may cover several items. | Nouls | 0.60 |
| frequency | How often is the amount in `amounts.mN` paid or charged? | monthly, annual, per_semester, one_off, instalments, not_stated. monthly = per month, monthly, ayda, aylıq, в месяц, ежемесячно, her ay, 매월 or 월; instalments = a stated number of payments | 0.60 |
| duration | For how long is the amount in `amounts.mN` paid? | whole_programme, first_year_only, from_second_year, one_semester, two_semesters, during_mobility_or_internship, until_next_assessment, other, not_stated | 0.60 |
| bound | Is the amount in `amounts.mN` an exact sum, a maximum ("up to"), a minimum ("at least"), or approximate? | exact, up_to, at_least, approximately, not_stated. `range` is set by CODE, never asked: a span inside "A~B", "A–B", "A-B", "between A and B", "entre A et B", "от A до B" or "A ilə B arası" is a range (Jev scored 0/3 on ranges). Asked only of single amounts. | 0.85 |
| amount_for_pK | Does `amounts.mN` apply to applicants from `places.pK`? (one Noul per place candidate on the amount's own line or header) plus `amount_for_all`: Does `amounts.mN` apply to all applicants alike? | Nouls | 0.60 |
| amount_for_level | Which study level does the amount in `amounts.mN` apply to? | the level candidates on its line or header + `all_levels` + not_stated. A line naming bachelor's and master's scholarships with different sums gets one answer per amount | 0.60 |
| amount_for_X | Does the text state that the amount in `amounts.mN` is for X? One Noul per beneficiary X: `student`, `spouse_or_partner`, `children`, `family_or_dependants` | Nouls, so one amount may be for several ("return airfare for the scholar and dependants" = student + family_or_dependants). TRUE: the text names who the money is for ("for accompanying family members", "per child", "Familienzuschlag", "ailə üzvləri üçün", "на членов семьи", "eş ve çocuklar"). A sum paid to the student with no beneficiary named is `student`. Separate from `pays`: a family allowance the student receives is still `paid_to_student`. Conditions on it ("if the spouse stays at least N months", "children under 18") are that amount's `requires_cN` | 0.85 |
| amount_intake | Which intake or year does the amount in `amounts.mN` apply to? | the intake candidates on its line or header + not_stated | 0.60 |
| date_role | What is the date in `dates.dN`? | application_deadline, application_opening, fee_deadline, application_period, results_announced, selection_or_award, funding_period, programme_start, page_published_or_updated, other, not_stated Asked once per date *range* when code finds one. Definitions v3 (§5.2.1): an `application_*` role is only a date for applying to THIS award; an olympiad, exam, event or other programme's date is `other` unless the page says applying happens through that event; "applications are open" with no date is no date. A table column header reaches Jev as context through a per-language cue table. | 0.85 |
| date_for_pK | Does `dates.dN` apply to applicants from `places.pK`? (one Noul per place candidate on the date's own line or header) plus `date_for_all`: Does `dates.dN` apply to all applicants alike? | Nouls | 0.60 |
| date_order | Only when code flags ambiguity: in `dates.dN`, is the first number the day or the month? | day_first, month_first, not_stated | 0.90 |
| duration | Which of `durations` states how long the funding lasts, not how long the programme is? Asked only when the presence Noul `has_duration` ("Do these lines state how long the funding lasts?") passes. | duration candidates + none; gated stratified by option count | 0.60 |
| holder_kind | Which kind of body gives the money described in these lines? | the closed `_HOLDER` list + not_stated | 0.60 |
| apply_here | Do these lines state that students apply to `page.organisation` itself for this money? | Noul | 0.60 |
| apply_elsewhere | Do these lines state that students apply to a different organisation than `page.organisation` for this money? | Noul | 0.60 |
| institution_wide | Do these lines state that students of any programme at `page.organisation` can receive this money? | Noul | 0.60 |
| route | How does a student obtain this money? | the closed `_Route` list + `other` + `not_stated` | 0.60 |
| route_order | When the money and the admission are applied for separately, which comes first? | `before_admission`, `after_admission`, `parallel`, `not_stated`. Asked only when `route` is not CONSIDERED_WITH_ADMISSION | 0.85 |
| renewal_condition | Do these lines state a condition for keeping or renewing the award after its first period (a grade to maintain, credits per year, an annual report)? | Noul. The condition is then a `requires_cN` on the award, marked as a renewal condition, never as a condition for applying | 0.60 |
| money_form | What form does the money take? | the closed `_Money` list + `other` + `not_stated` | 0.60 |
| tuition_level | How much of tuition does this award cover? | none, partial, full, not_stated. Criteria: "the programme does not pay X" ("Xarici universitetə təhsil haqqı ödənilmir") is `none` for X, never a waiver; a waiver says the student is not charged | 0.60 |
| living_level | How much of living costs does this award cover? | none, partial, full, not_stated | 0.60 |
| internationals | Do these lines state that international or foreign students are eligible? | Noul. Since 2026-10-12 (§5.2.1) a "yes" here is **not** a nationality condition. It starts the site hunt for the funder's named list, and only when none is found does it become "all countries except the host" | 0.60 |
| extra_* | Do these lines state that the award includes `travel` / `insurance` / `housing` / `a language year` / `visa support`? | five Nouls | 0.60 |
| obligation_* | Do these lines state that the holder must `return home` / `work in the host country` / `serve the funder` / `repay if a condition is broken`? | four Nouls | 0.60 |
| discontinued | Do these lines state that this award is discontinued or not offered in the coming round? | Noul | 0.70 to hide |
| window_closed | Do these lines state that applications for this award are currently closed? | Noul | 0.60; a note on the card, never hides |
| eligible_pN | Do these lines state that applicants connected to `places.pN` can apply, as citizens or residents of it, or as students of an institution whose name contains it? | Noul. Owner: students of "Azərbaycan Dövlət Aqrar Universiteti" can apply = yes; "Française / EU" = French or EU applicants = yes. Measured 2/4, needs more data | 0.60 |
| eligibility_elsewhere | Do these lines say the list of who may apply is given somewhere else (an agreement, a country list, a drop-down menu, another page)? | Noul. When it passes, `nationality_shape` = `stated_elsewhere`, never `not_stated` or `open`, and code follows the pointer: the linked page, or the drop-down's options from the rendered page through the vendor rung (owner: "the agent should go and find the countries") | 0.60 |
| excluded_pN | Do these lines state that applicants from `places.pN` cannot apply? | Noul | 0.90 to exclude |
| requires_cN | Do these lines state `requirements.cN` as a condition for applying? | Noul, per level, language, grade or age; since 2026-10-12 also per required test or certificate (SAT/ACT, a copy of a language certificate, with or without a threshold), `prior_degree`, `excluded_degree`, residence limit, stateless persons and compatriots abroad (§5.2.1) | 0.60 |
| target_level | Which degree level is this award track for? | `master`, `bachelor`, `phd`, `postdoc` (never student-facing), `any`, `not_stated` (§3.1). Criteria (definitions v3, §5.2.1): TRUE = the level the award is FOR. FALSE = a prerequisite: a degree the applicant must have completed ("you must have completed a first degree", "2 years' work after the bachelor's") is a `requires_cN` of kind `prior_degree`, and "PhD holders cannot apply" is one of kind `excluded_degree`. Year-of-study wording ("1st–3rd year students", "I, II və III kurs", "3–4 курс бакалавриата") names the level through the per-country table, by code. *(Superseded 2026-10-12: the 2026-10-05 example "you study in a master's or 3rd–4th year bachelor's" → `requires_cN`; year-of-study wording now names the level.)* | 0.85 |
| funding_period | Do these lines state the years during which this award is funded or offered? | Noul; code reads the years from the intake candidates (§5.5) | 0.60 |
| name | Which of these is the award's name? | heading, page title, first-line candidates + none; presence from `is_award_name`; gated stratified by option count | 0.60 |

Code derives from these: `scope` (§5 step 6: `POINTER` when `apply_elsewhere` passes and `apply_here` does not; when both pass the page contradicts itself and the card is stored, not shown; otherwise from `institution_wide` and the page's kind), `nationality_shape` (from the eligible and excluded places), the date itself, the duration in months, and every benefit row.

**Bars follow the cost of a mistake:** a shown sum or date needs 0.85 because a student acts on it; excluding a student needs 0.90 because hiding a real award is the costlier error; flagging a line needs only 0.35; labels need 0.60. The first measurement (§7.1) put Jev at about 88% on `pays` before `benefit_in_kind` existed, 94% on `covers` and `bound`, 98% on `period`. *These bars are Jev probabilities. Under the slice-2 reader a value stands on the pair's agreement or on Opus's answer to a split (§5.5). Each field kind's error is certified on the owner's gold set, and where Jev runs as a filter its bars still apply.*

### 5.2.1 Definitions v3 and country groups (owner, 2026-10-11/12)

These are the question criteria every reader gets, and they replace any older criterion that differs. Measured as the "Amended" rules of `slice2-spike/v2/questions-v2.md`.

**Level** (`target_level`, `requires_cN`):
- The level is the **target** level, the one the award is *for*.
- **A prerequisite is never the level.** "Completed a first degree" and "2 years' work after the bachelor's" are `requires_cN` of kind `prior_degree` (the required prior degree). "PhD holders cannot apply" is a `requires_cN` of kind `excluded_degree` (an exclusion).
- **Year-of-study wording maps to a level by code**, through a per-country data table, `docs/research/year-of-study-levels.csv`:
  - columns `country,locale,pattern,years,level,source_url`;
  - seed examples from the owner: en "1st–3rd year students", az "I, II və III kurs" and ru "3–4 курс бакалавриата", each naming `bachelor` for its country;
  - every row cites its country's own source for the bachelor's length;
  - a phrase in a country with no row is `no_candidate`: counted, never guessed.

**Nationality** (`eligible_pN`, `excluded_pN`, `nationality_shape`):
- **A condition is a named list:** countries, regions or citizenships, included or excluded ("citizens of Azerbaijan", "Türkiye Cumhuriyeti vatandaşı", "граждане КНР", "EU/EEA", a named country list).
- **Generic "international students", "foreign students" or "иностранные граждане" is not a condition.**
  - It triggers the site hunt (§5.5 step 4) for the funder's own list.
  - If none is found, the award is open to all countries except the host.
- **The basis is recorded:** whether the funder tests **citizenship** or **residence** (`place_basis`: `citizenship`, `residence`, `both`, `not_stated`). DAAD Helmut-Schmidt, for example, tests where the applicant lives and applies from, not their passport.
- **Residence limits** ("not resident in Germany for more than 15 months"), **stateless persons** and **compatriots abroad** (соотечественники) are eligibility conditions, recorded as `requires_cN`.
  - Like every fixed fact, each must be verified as met by the student's verified profile, or the award is hidden (§5.5).
  - The profile fields for residence history and compatriot status are not defined here. They belong to the tailored-programme build, as in §3.2.

**Application dates** (`date_role`):
- These are dates of applying to **this** award.
- An olympiad, exam, event or competition-stage date, or another programme's date, is never an award date, unless the page says applying to this award happens through that event.
- "Applications are open", or "have started", with no date is not a date.

**Requirements** (`requires_cN`): a required test or certificate counts even with no threshold, for example SAT/ACT or a copy of a language certificate.

**Country groups: the funder's own list always comes first.** That includes a linked PDF, a "list of countries" tab or an annex; when one exists, it is used. Only a page that names a group and gives no list falls back to this table. Each list is bound to the page's date, and evidence is in `docs/superpowers/research/2026-10-12-country-group-standard-lists.md` and `docs/superpowers/research/2026-10-12-country-group-policy.md`.

| phrase on the page | fallback when the funder gives no list |
|---|---|
| CIS / СНГ / государства-участники СНГ | AZ AM BY KZ KG TJ TM UZ. MD is included while the page predates 2027-04-08, when Moldova's exit takes effect (Rossotrudnichestvo's 2026 list). Ukraine goes to the **hold queue**. Georgia and Türkiye are **not eligible** |
| "developing countries" (and "developing and emerging" without a list) | Off the OECD DAC list of ODA recipients: **not eligible**. On it: **hold queue**, unless the page itself says DAC or ODA, in which case the DAC list applies |
| "Global South", "emerging economies", "newly industrialised" | **hold queue** |
| "low- and middle-income" | World Bank income groups, LMY, but only when that phrase is the whole criterion. With a qualifier, or a bare "LMIC": **hold queue** |
| LDC / least developed countries | The UN M49 table's LDC column. Re-check after the 2026-11-24 graduations |
| Sub-Saharan Africa | The funder's system list (for example, Erasmus+ Region 9). Otherwise UN M49 region 202, with Sudan and Djibouti sent to the **hold queue** |
| EU, EEA, Western Balkans, Eastern Partnership, ASEAN, African Union, Commonwealth | The existing `regions.py` rows (§5 step 4) |

A "hold queue" entry hides the award from every student until the operator acts (§0.29, §5.5 step 6). Round 2 counts how often these phrases appear (§5.5), which tests the 15% ceiling.

### 5.3 Languages

*Since 2026-10-12 the readers are those of §5. Where this section says Jev reads a page, read it as "the readers". The no-translation rule and the per-language checks are unchanged.*

- **Owner, 2026-10-03, final: no translation. Jev reads every page in its own language.** This reverses the same day's "English only" decision, because both measurements showed translation adds nothing once questions carry criteria (decision engine §1/§3.10). A translated arm survives only as a **measured rescue** for a language that fails its bar, never as a default. Code still copies every value from the original line. *(Record: an earlier bullet here said Jev reads English through a per-language translator; that is withdrawn.)*
- *(Record)* Jev reads the page in its own language by default. No translation model runs in the reader unless §7 shows a translated arm winning for a language and the owner accepts it.
- **Code carries the language.** Month names, currency words and place names are data tables per language (currency forms already are); a language is added by adding rows.
- **What is measured per language:** wording A against B, and each with and without the `note` field naming the language. Whichever passes at the bar ships for that language.
- **A language that has not passed shows nothing** (§0.10): no card, no name, no link. A language passes when its share of the gold set (§5.5) meets the certified bounds. Bars are set pooled across languages, then each language is checked (decision engine §1). Azerbaijani, Turkish and Russian are the core of the launch, so their gold-set facts are drawn first.

- **Translation is measured, not assumed away (owner, 2026-09-28).** Published work finds that small English-first models read machine-translated text better, by about ten points in one study, while no one has measured Jev. So §7 runs Jev four ways on the same questions: the original text; the original with a `note` naming the language; a line-by-line English translation with each line's id kept; and the original and the translation side by side. If a translated arm wins for a language, it ships for that language under two rules. Code still finds and copies every amount, date and quote from the **original** line, so a translation error can mislead a judgment but never put a wrong value on a card. And the translation comes from a model other than Jev, which is a writing model in front of the reader, so it is the owner's call per language, taken on §7's numbers.

### 5.4 Deciding what to fetch, without discarding a real award

Once reading costs about 0.2 cents a page, **fetching becomes the main cost** (1 Firecrawl credit per page, 25 on scrape.do). *(That was the Jev-only figure. With the slice-2 readers at about 1–2¢ a page, a skipped page saves its read as well as its fetch. The fail-open rules below are unchanged.)* Three filters cut it, all first specified in `2026-09-22-typed-decisions-and-multilingual-sources-design.md` (D1–D3) and not yet built. They are filters, not the reader. Jev is their specified model, and it ships only on its measurement (owner, 2026-10-12: Jev may return as a measured filter, never as a reader):

| filter | what Jev reads | what it saves |
|---|---|---|
| **F1 register pre-filter** (§3) | the register's name, purpose text and category for an organisation | all website work for a body that plainly does not fund students |
| **F2 search-result triage** | the result's address, title and snippet, in memory only | the fetch of a result plainly not about funding |
| **F3 site-map ranking** | Firecrawl `/map`'s list of `{address, title}` for one site (1 credit for the whole list) | fetching every page of a site; at most 25 are fetched, likeliest first |

**One engine, generic from the start** (owner, 2026-10-09). There is one question-set interface: candidates in; typed decisions with byte-exact quotes, link-candidate answers and the site-hunt step out. Funding is the first question set, application routes (§3.4) the second and document file rules (§3.5) the third. All three read the one reader list (§5).

**Catalogue access** (owner, 2026-10-09). An agency that buys the platform never browses, exports or bulk-reads the catalogue. Its students see awards from it, and nothing more.

**Discarding a real award is the one mistake that is never seen**: a skipped page is never read, so no card, no student and no audit ever shows what it held. The reader fails closed (unsure hides the award, §5.5). **The filters fail open** (unsure means fetch). Every filter follows these rules:

1. **Skip only on positive evidence.** A filter never skips because relevance is merely *low*. It skips only when the keep questions all fall below a low bar **and** a noise question states what the item is instead (a news item, a staff profile, a login page, a body whose stated purpose is unrelated to education). A bare address with no title, an empty snippet, or an unreadable register row is kept.
2. **Keep questions are broad, narrow-worded Nouls, combined with OR in code.** One property each, per §5.1, for example: "Does this title or address mention a scholarship, grant, stipend, bursary or financial aid?"; "…tuition fees or a fee waiver?" (fee pages carry waivers); "…admission or how to apply?" (funding often sits on the admission page); "…international students?". The bar to keep is **any one of them at P ≥ 0.2**. The bar is low on purpose: a wasted fetch costs 1 credit, a missed award costs the student the award.
3. **The address and title are often not in English.** The questions stay English (§5.1). §7 measures each filter with and without the translated title and a `note`, exactly as for the reader.
4. **A Choice never excludes.** F3's Choice over the site-map ids is a *ranking*, whose probabilities sum to 1 across the list, so thirty relevant pages each get about 0.03. It sets the order in which the 25 pages are fetched and nothing else. Whether an address is skipped is decided only by its own Nouls (rule 2).
5. **A failed decision keeps.** A Jev outage, a refusal, a state over the token limit or a skipped question means fetch, bounded only by the existing per-run and per-month budgets. It is never "skip for now".
6. **F1 excludes only on a stated fact.** "Does this text state that the body funds only citizens or residents of its own country?" at P ≥ 0.9, or a register category code that names an unrelated activity. "Does this body give money to students?" answering *low* is not enough; it may keep `unknown`, which stays a candidate (§3).
7. **Skips are recorded.** Every skipped item is written with the probabilities that skipped it, so a later audit can reopen it. **For F2 the record is the URL and the probabilities only.** A search result's title and snippet are a provider object, and `CLAUDE.md`'s search-provider rule ("nothing from a provider object is persisted") holds here. An audit re-fetches the URL; it never needs the snippet.
8. **The 25-page cap is not a skip.** F3 pages beyond the 25th that pass a keep question are **deferred**: recorded, counted, and fetched first the next time a student needs this organisation. A page dropped by the cap with no evidence about it would break rule 1. The count of deferred pages per site is reported, so a cap that bites often shows up.

**Measurement (in §7's harness, before any filter ships):**
- **Recall, not accuracy.** For a set of sites and search results, everything is fetched and read once, including what each filter would skip. The key (§7) marks which items carry a real award or requirement. A filter's score is **awards on skipped items**, and it must be **zero** on the measurement set. A filter with a miss ships at a looser bar or not at all. The savings (fetches avoided) are reported beside it, never instead of it.
- **Continuing audit:** in production, **1 skipped item in 20** is fetched and read anyway (about 0.1 credit per skip). An award found there raises an alarm and triggers re-measurement of that filter.
- **Cost of measuring:** about 20 sites × up to 60 pages ≈ 1,200 credits (about $1) plus reading, once.

### 5.5 Part F — verification: what a student may see, and how it stays true

**Serve rule (owner, 2026-10-12; provisional until round 2 confirms it).**
- **Agreement accepts a value.** DeepSeek V4.1 Flash and GPT-6-luna answer the same question over the award and its section (§5). When they agree, and code's checks pass on the quote, the value is accepted.
- **A split goes to Claude Opus 5.5,** which is asked the same question over the same section and decides. Its answer must pass the same code checks.
- **Not in the rule:** Sonnet, Jev and Kimi K3.
- **What happens when it fails:** a value the rule cannot accept goes to the site hunt (step 4), and then to the hold queue (step 6). It is never shown as a guess.
- **Certification:** each field kind's error is certified on the owner's gold set (below). Until a certification batch (`GoldItem` purpose=certification) exists, the 1% target is provisional.
- **Every value records which reader answered what** (the per-value agreement record of §11.1).
- **Measured:** precision 0.980 and recall 0.925 on 211 owner-judged hard cards (§5, `slice2-spike/v2/`).

*Superseded 2026-10-12. The rule below is kept as the record.* **Reason:** on the owner-judged hard cards, Jev + Kimi K3 under the old definitions kept a recall of only 0.25. DeepSeek + Luna with Opus on a split reached precision 0.980 and recall 0.925 under definitions v3 (`~/agent-workspace/elmify-runs/slice2-spike/`). Adding Sonnet or a third reader changed 1–3 of 211 cards.
- *Serve rule until certification (owner, 2026-10-05, recorded through elmify-82):*
  - *Agreement shows a value: a value is shown only when Jev and Kimi K3 agree at the question's bar. Kimi K3 is `moonshotai/kimi-k3` on host makora, thinking off, eight lines a call.*
  - *Disagreement goes to Claude Sonnet 5.5, asked the same closed question. The value stands only when Sonnet sides with one of the two (2 of 3); otherwise the award is hidden and climbs the ladder. Sonnet never decides alone.*
  - *Bars are provisional until a certification batch sets them.*
  - *Measured then: Jev ≥0.8 with Kimi ≥0.8 against the model-built key on 1,400 lines, 238 yes and 3 wrong (precision 0.973 → 0.987). Sonnet 5.5 scored 87/100 on Jev's unsure band in the harness, but 14/39 on the owner's gold under the old definitions.*

Owner decisions of 2026-10-03 (§0.10–16), from a grilling session. Research behind the statistics: `.context/research/2026-10-03-reliable-extraction-engine.md`. The application stage follows the card, so a value a student acts on cannot be a guess. A student sees **only verified awards they can apply to**.

**Targets** (owner, 2026-10-08 to 2026-10-12, from the slice-2 grilling; §0.28):
- at most 1% wrong on shown fields, per field kind, deadlines included, precision first (§0.13);
- at most $0.25 of model spend per page (the measured design costs about $0.01–0.02);
- the background catalogue sweep is batch-priced and may take hours per page; under 30 s only for a page a student waits on (a typed programme, an on-demand single-page read). *(Superseded 2026-10-12: "under 30 s per page, including the background sweep", from 2026-10-08/09.)*

The first job is the catalogue sweep.

**What makes a value verified** (all four, in this order):
1. **Code** copied the value verbatim from the official page's original line, and code's checks pass: the date is a real calendar date with a year, the deadline lies in the future (or the award is shown as "expected", below), the number and currency sit on the line, and the line belongs to this award.
2. **The two readers agree, or Opus settles their split** (the serve rule above, §5). This holds for every field kind. Each answer's quote passes the byte-exact check.
3. **The rule's error is certified as one joint rule** on the owner's gold set (below), never by multiplying the readers' error rates. The research measured that when two LLMs are both wrong, they give the same wrong answer about 60% of the time, so independence cannot be assumed. The slice-2 spike agrees: the errors left are shared by every model.
   *Superseded 2026-10-12, kept as the record:*
   - *2. Jev answered at or above that question's certified bar, with order-swapped pairs agreeing where §5.2 asks for them.*
   - *3. A second independent reader agrees for deadlines, eligibility and documents (decision engine §3.3).*
4. **The rest of the site comes before any model** (owner, 2026-10-09: "these uncertain facts are somewhere on the website"). A fact goes to the site hunt when it has no candidate on the page, when it is pointed to elsewhere (`eligibility_elsewhere`, `apply_elsewhere`, or a generic "international students" with no named list, §5.2.1), or when the readers' disagreement is still unresolved. The hunt looks first on the other pages of the same proven site. This goes through the existing funnel, `apps/research/sitejob.py`, whose stages return URLs only, cheapest first:
   - `DOCUMENTS`: links on the page and the documents they lead to, such as the call text, guidelines, FAQ, a country list or a PDF;
   - `MAP` and `GUIDED_MAP`: the site map filtered by that fact's own vocabulary (who can apply, documents, deadline, fees, how to apply);
   - `NAVIGATOR`: only when the cheaper stages found nothing.

   Every page found must pass Part B: on the proven site, or an `ApplicationSystem` host linked from it (§3.4).
   - **Another official domain counts** (owner, 2026-10-09). The hunt may follow a link to a different domain when that domain passes the same Part B check: a university page leading to `edu.gov.az`, Bolashak to `adilet.zan.kz`, a news page to `chevening.org`. In a 15-page spike, same-domain links found 6 of 29 missing fields, and 19 of the other 23 sat on another official domain (`~/agent-workspace/elmify-runs/slice2-spike/hunt/summary.md`).
   - **Strict attach.** A hunted value attaches to an award only when the page or section it came from names that same award or scheme, matched by code. Otherwise it is discarded. A Bolashak page's window "с 30 марта по 31 мая 2026" belongs to a different, in-country scheme and must never reach the Bolashak card.
   - **Last cycle's value is shown, labelled** ("Last cycle: deadline 15 Jan 2026, new date not announced yet", with its source). It is not held and not hidden, as for "expected to open" below. It is read by the same engine, and its facts carry their own source URL and quote. When two pages state different values for one fact, **the newest page wins and is shown** (owner, 2026-10-09).
   - "Newest" is the cycle the page itself states ("2026/27", "2027 call", a dated announcement), parsed by code from a quote. The higher cycle wins. `Last-Modified` or the crawl date only breaks a tie.
   - A page stating a cycle beats one stating none, as long as both passed Part B (owner, 2026-10-09: "if a website is legit and it states the cycle then it wins").
   - Only two cases go to the hold queue (step 6): neither page states a cycle or date, or both state the same cycle with different values. **Cap:** 6 extra pages per award per cycle, charged to the platform budget. An unchanged page is free (`content_sha256`).
5. **Unsure is a ladder, not a verdict.** The ladder is the serve rule, then the site hunt: the pair, then Opus on a split, then the other pages (step 4). Every step is paid from the platform budget. A fact still unresolved after that sends its award to the hold queue (step 6), and it is never shown as a guess or as "not stated". *(Superseded 2026-10-12: the ladder of an order-swapped Jev pair, then a second reader, then a strong model, from decision engine §3.3.)*
6. **The hold queue: nothing is hidden silently** (owner, 2026-10-09 and 2026-10-12; §0.29). An award goes into a queue for the **platform operator** when it has any of these:
   - a fact the site hunt could not find;
   - a reader disagreement the ladder could not settle;
   - two conflicting pages the cycle rule of step 4 cannot order;
   - a country group the fallback holds (§5.2.1).

   It stays hidden from every student, B2C and agency alike, until the operator acts.
   - **The operator fixes the wording, never the value:** the question's wording or criteria, a finder, an example, or a data row (a `regions.py` row, a year-of-study row, a placeholder word). A one-off value is never typed in. Then they re-run, and the fixed wording applies to every page, which is how the system improves as it runs.
   - The retired `manage.py funding_review` comes back in this narrower role. It is a platform action, never a tenant one. Agencies never browse, export or bulk-read the catalogue (§5.4).
   - **Up to 15% of real awards** may sit in the queue before the reader counts as failing.

**What the student must meet.**
- **Nationality** (definitions v3, §5.2.1).
  - A page silent on whether an Azerbaijani citizen may apply, or one that says only "international students", sends the site rung (step 4) to the eligibility, FAQ or "who can apply" pages first. If the funder's list is not found, a generic phrase means all countries except the host.
  - A statement naming a group counts through the funder's own list first, then through the fallback table of §5.2.1. So "developing countries" with no list holds an Azerbaijani applicant's award, since Azerbaijan is on the DAC list, while a page that names the DAC list expands to it.
  - Whether the funder tests citizenship or residence is recorded, and the student is matched on that fact.
- **Fixed facts must be verified as met by the student's own verified profile**, or the award is hidden: nationality, age, degree held, grades already awarded (with their scale), and since 2026-10-12 residence limits, statelessness and compatriot status (§5.2.1).
- **Attainable facts become Application Kit tasks.** A language test not yet taken, or a document still to obtain, is shown as "eligible if you have IELTS 6.5 by 20 February", with the task's own deadline.
- Wrongly hiding an award from an eligible student is the accepted error (§0.11). Wrongly telling a student "eligible" is not.

**Between cycles: "expected to open".** The recommendation kit plans a whole admission cycle, not only what is open today. So a recurring award whose new call is not yet published stays in the kit as **"expected to open in February"**, under two conditions:
- **It is recurring:** `funding/validity.py::cycle_validity`'s existing rule of two dated past cycles.
- **No funding-end signal covers the coming cycle**, for example "funded 2020–2026" when the coming intake is 2027. This needs one more §5.2 question, `funding_period`: "Do these lines state the years during which this award is funded or offered?" Code reads the years from the intake candidates and compares them; no reader compares dates.

Everything shown about the past cycle is labelled as the past cycle. The award joins the reminder ladder once the new call is published and verified.

**Freshness: one rule** (§0.16). A check is 1 Firecrawl credit with `changeTracking`, about 0.08¢. A changed page is re-read whole: about 1–2¢ with the slice-2 readers, at standard price when a student is waiting and batch price otherwise. *(The cost lines below were computed at the Jev-only 0.25¢ re-read and are re-derived from the sweep's measured cost.)* Any change re-runs verification, and the award is hidden until it passes again.

| award | checked |
|---|---|
| a student is applying to it | at Application Kit start; before every reminder in the ladder (14, 7, 3 and 1 days before the deadline) |
| in some student's pack, or in the pre-built core | monthly; weekly during the month the new call is expected, until new dates appear |
| any award, at the moment it is shown | if the last check is over 30 days old, checked first (synchronously, seconds) |

- **Cost:** about 1–2¢ per tracked award per year, plus about 0.4¢ per award a student applies to. For 2,000 tracked awards that is about $25 a year.
- **The schedule** is one daily job (an EventBridge rule on `WorkerTaskDefinition`, modelled on `EuropassCanaryRule`).
- **Why these points:** a deadline *extension* is harmless (our date is earlier than the real one); a deadline brought *forward*, a closure and a new cycle are the dangerous changes. So checks sit where the student commits effort and where the cycle turns.

**Certification: the owner's gold set.** A model-built key proves only that the reader agrees with the referee model, not that it is right. So the bounds are certified against the owner's own checks.

| fact kind | at most wrong (95% confidence) | gold facts, zero errors | owner time |
|---|---|---|---|
| every field kind (deadline, eligibility condition, document item, amount and its kinds, route fields) | 1 in 100 | 299 per kind | about 1 h per kind (about 10 s each) |

- **The arithmetic.** With zero errors, *n* accepted facts bound the error rate at 1 − 0.05^(1/*n*). One error raises 299 to 473. These are the research note's figures, and plan 1 recomputes them in code.
- **Threshold setting is Learn-then-Test** (the Trust-or-Escalate procedure; MAPIE's `BinaryClassificationController` implements it). For each fact kind, the procedure tests thresholds from strictest to loosest, takes the exact binomial upper bound on errors among the accepted gold facts, and stops at the last threshold still inside the bound. Facts below the threshold climb the ladder; they are never shown.
- **Strata are pooled across languages for the bar, then each language is checked** (decision engine §1). A language whose own gold facts cannot meet the bound shows nothing (§5.3).
- **Pages:** about 600–1,000 pages are fetched to find 3,000 deadline facts, for about $1–3.
- **Improvement rounds first, then one fresh certification batch.**
  - The owner checks rounds of about 200 facts. Each round's errors fix finders, wordings or bars, and the rounds repeat until one comes back clean.
  - Then **one certification batch of fresh facts** is checked after the last change. Facts used to find and fix errors never certify the engine that was fixed with them.
  - Every later change re-certifies only what it touched: a reader's model, version or host pin, a reworded question, a new language, a new translator.
- **Round 2 (owner, 2026-10-12): after slice 2, before certification.**
  - **The sample:** about 250 card values on about 35 fresh pages, drawn at random from real sources (EACEA, the funder seeds, the destination list), about 3 pages per language: en, de, fr, es, it, nl, ko, ja, zh, az, tr, ru and kk.
  - **The check:** the owner answers each value blind on the staff page below; no model pre-answers (owner decision 2026-10-12, §7).
  - **What it settles:**
    - it confirms or replaces the provisional reader stack (§5);
    - it counts how often vague country phrases appear, which tests the hold queue's 15% ceiling (§5.2.1).
  - Like every improvement round, its facts never certify.
- **The gold labels are kept forever,** in the repository's test data. They are the proof behind "verified" and a regression suite every later change runs against.
- **The checking page is an internal staff tool** (owner, 2026-10-03), never student-facing. It is a staff-only page in the Django app, behind login and MFA. Each item shows:
  - the official sentence, highlighted in its page context;
  - the engine's answer;
  - buttons **✓ Correct**, **✗ Wrong** and **Not on page**; on ✗, the owner types or picks the correct value.

  It has keyboard shortcuts, a progress bar and a language filter. Labels go into a table the harness reads directly.
- **Production monitoring:** the 1-in-20 audit (§7) runs a Bernoulli sequential test (SPRT/CUSUM, or MAPIE's `RiskMonitoring`). It needs about 180 audits on average to detect a rise from 1% to 3%, and about 600 for 1% to 2% (research note; my arithmetic, not quoted). An alarm hides the affected fact kind and language until it is re-certified.

## 6. Part D — one reader, cheap models, a harness instead of a vote

### 6.1 One reader per decision

*Superseded 2026-10-03 by `2026-10-03-one-decision-engine-design.md` §3: Jev first, and a cheap second reader asked only inside Jev's measured uncertain band. Kept below as the record.*

The three-reading vote is retired where each part is rebuilt:
- the funding judge here;
- the CV-format judge (`derive.py`) and the research-fit judge, as typed-decisions already plans.

Agreement between readers survives only as measurement (§7), never as a production gate.

### 6.2 The harness: verify by code first, by Jev only for judgments

*For the funding reader, superseded 2026-10-12 by §5. Code still verifies first, and item 2 below stands. But readers may propose quotes (kept only when byte-exact), the judging readers are DeepSeek V4.1 Flash and GPT-6-luna, and Opus decides a split, so "Jev judges" and "no stronger-model retry" are the record. The letter part is governed by the letter design, as stated below.*

**Asking Jev "is this made up?" is a judgment, and it costs a question.** Asking code "is this text on the page?" is free and certain. So the harness is ordered cheapest and surest first:

1. **In the reader, no model produces text at all.** Code finds every candidate; a line whose value code cannot find is `no_candidate`, counted and shown as text (§5).
2. **Code verifies:**
   - the quote is verbatim on the line;
   - the number and currency are on it;
   - the date is valid and has a year;
   - the intake is not a past one.
3. **Jev judges only what code cannot:** roles, labels, and belonging.

There is no stronger-model retry in the reader.

**Letters and CVs are the one place generated prose is unavoidable.** Since 2026-09-28 they have their own master design, `2026-09-28-one-letter-engine-design.md` (commit 3ea6b8f2 on `claude/letter-gap-fixes`, not pushed, awaiting review). **That document governs** the writer model, the checks, the hosts and the censorship route. What follows in §6.2–§6.5 about letters is the earlier sketch it replaced, kept only for the record. Where the two differ, the letter design wins, and plan 2 here covers only the funding side of model routing. The earlier sketch: Jev checks the output in one call per letter:
- per sentence: "Does `letter[i]` claim something about the applicant that no item in `facts` supports?"
- per planned point: "Does the letter mention `plan[k]`?"

A flagged letter is regenerated once, naming the flagged sentence or the missing point. If it is still flagged, the existing letter gate (`is_letter_blocked`) blocks it. That costs about 0.05 cents a letter.

### 6.3 Which model

*For the funding reader and every question set on its engine, settled by the owner on 2026-10-12 (§5): DeepSeek V4.1 Flash and GPT-6-luna, with Opus 5.5 on a split. This section's rule (the cheapest that matches quality, versions pinned) is how round 2 confirms or replaces that choice.*

- **Candidates:** DeepSeek V4 Pro and Flash, Qwen 3.8, GLM 5.3, Kimi, MiniMax, and the current cheap OpenAI model.
- **Per task, the cheapest that matches quality on §7 wins.**
- Versions are pinned and re-measured when a version changes.
- **No stop-gap in today's reader.** Measured 2026-09-27: DeepSeek lost to Jev on every amount fact the referee decided (56 to 20) and returned off-format answers on 2 of 59 awards. Swapping it for Claude in the three-reading reader would buy little and delay the Jev reader; the Jev reader replaces that reader whole.

### 6.4 Student data

- **Before any model call, code strips direct identifiers:** name, e-mail, telephone, address, date of birth, ID numbers and photos.
- Letters and CVs are generated with placeholders, and code fills them in.
- A test asserts that no identifier reaches any prompt. This is the same shape as research-fit's `test_no_query_ever_carries_the_student`.
- **Jev may not see student text yet.** `docs/legal/2026-09-provider-terms.md` records TypeSafe as "candidate only. No real student text reaches Jev until this DPA is countersigned or accepted through the account and the sub-processor list has been read once."
  - The funding reader sends only public pages, so it is not blocked.
  - Every Jev check over a letter, a CV or a transcript is blocked until the DPA is accepted and OpenRouter's terms are reviewed, since Jev is reached through OpenRouter.
  - The transcript reader already enforces this with a setting checked before the document is opened (`TRANSCRIPT_JEV_ENABLED`, `apps/documents/transcript.py`). Any student-text Jev path added here copies that gate.
  - The acceptance is an owner action, and it goes before plan 2.
  - **Accepted by the owner, 2026-10-03:** TypeSafe's DPA and OpenRouter's terms.
    - The sub-processor list (`trust.typesafe.ai`, which renders only in a browser) was read the same day: Amazon Web Services, Modal, Slack and Google Workspace, all USA. Modal processes prompts and does not store them.
    - An update dated 2026-10-03 adds **Nebius and CoreWeave**. The DPA's 15-day objection window (§3.1) runs on that change.
    - Still owed: recording the acceptance in `docs/legal/2026-09-provider-terms.md` on master. Turning `TRANSCRIPT_JEV_ENABLED` on is a separate deploy decision.

### 6.5 Censorship

Chinese hosts filter topics such as Taiwan, Tibet, Xinjiang and Hong Kong. A letter for a Taiwan scholarship, or for human-rights study, can come back refused or quietly softened.
- **Detection:** a refusal, or a planned point that §6.2's per-point question finds missing.
- **Response:** that call is redone on a non-Chinese host.
- §7's set includes such cases, so a model that fails them is known before it ships.

## 7. Part E — measuring without people, for a few dollars

- **The set:** 50 real pages chosen for Azerbaijani students:
  - Stipendium Hungaricum, Türkiye Bursları, DAAD, Chevening, GKS, MEXT, CSC;
  - Erasmus Mundus programmes;
  - Azerbaijan's state programme;
  - universities' own international scholarships.

  It reuses the 65 funding-page URLs saved by the 2026-09-16 run. It includes pages and lines that state no funding, because a read that finds nothing must be scored as well.
- **The answer key is built by a reader that is not the one being tested.**
  - One cheap model from a different company reads each page.
  - Code compares its card with Jev's card:
    - where they agree, the fact enters the key;
    - where they disagree, a strong model decides, asked only about the disputed facts;
    - a random 10% of agreements also go to the strong model, to measure errors both readers share.
  - When a model itself is being tested, the key's reader comes from another company, so no model grades itself.
  - Defaults:
    - the key's reader is DeepSeek V4 Pro, or `gpt-5.6-luna` when DeepSeek is the one being tested;
    - the strong model is `gpt-5.6-sol`, or Claude Opus 5.5 when OpenAI's cheap model is on trial.
  - *Since 2026-10-12 the reader under test is the §5 stack, so where this section says Jev, read "the reader under test". These defaults name DeepSeek, OpenAI and Anthropic models, which are all now in that stack, so under "no model grades itself" they can no longer build its key. **Owner decision 2026-10-12: there is no model-built key for the §5 stack.** Tuning and certification rest on the owner's own verdicts only, and owner check pages show no model pre-answers (the owner answers blind), so nothing the stack produces is ever graded by a model from the stack or by a model whose answers the owner merely confirms.*
- **Scores:** per fact type and per language, with the negatives counted.
- **Wording is tested too.** The vendor says wording, not repetition, is where Jev's answers vary. Each question in §5.1 ships with two wordings, and the better-scoring one is kept, with the loser's score written beside it.
- **Cost:** about **$1.50–3** in total. Fetching is about 5 cents, and Jev on 50 pages is under 10 cents.
- **Continuing audit:** in production, 1 page in 20 gets the same check (about 1 cent). The key keeps growing, and a fall in agreement triggers re-measurement.
- **Limit:** 50 pages detect a real quality gap. They are not enough to tune every language.

**Certification is no longer model-built** (§0.12, §5.5). The model-built key below still tunes wordings, arms and bars during the improvement rounds and runs the production audit. The bounds a student relies on are certified against the owner's gold set.

**Since 2026-10-03 this harness is part of the shared one in `2026-10-03-one-decision-engine-design.md` §6, and that document's §6.3 targets govern the pass bars** (0.98 precision on shown values, 0.99 on excluding a student, 0.95 on labels, zero awards on skipped items). The sections above stay as the funding reader's part of that harness: its page set, its questions and its cost.

**What the 2026-10-03 review adds to the funding part of the shared harness** (each closes a gap the sections above leave open; to be carried into the decision-engine document's §6 when it is next revised):

- **The key's reader reads the whole page, not Call 1's flagged lines.** A funding line Call 1 misses is otherwise invisible to the key, and Call 1's recall is never measured. The same goes for section selection (§5 step 1): the key reads the page before `_FUNDING_TERMS` selection, so a section the term list drops counts as a miss.
- **Languages need their own pages.** Per-language bars cannot come from a set where a language has one page (the 15-page run had one Azerbaijani line). *Set approved by the owner, 2026-10-03, about 80 pages:*
  - English 30;
  - Turkish 10, Russian 10, Azerbaijani up to 10;
  - German, French and Hungarian 10 together;
  - Chinese, Japanese and Korean 10 together.

  A language with fewer than 5 pages or fewer than 30 keyed facts is reported as **unmeasured**, never as passed. Azerbaijani may have fewer than 10 real funding pages; then the set takes all of them.
- **Tune on half, score on the other half.** Bars, wordings and the translation arm are chosen on one random half of the pages and reported on the other half. Choosing among two wordings, four language arms and a bar per question on the same 50 pages that score them would report the luck of the draw as accuracy.
- **What "passes" means:** the decision engine's §6.3 targets, plus three things it does not yet say.
  1. The targets are met on the **scoring half** (above), not on the half they were tuned on.
  2. Every score is reported with its 95% Wilson interval, because 98 right out of 100 has a lower bound of 0.93 (computed 2026-10-03). Requiring the lower bound to clear 0.98 takes 189 shown values with no error, 280 with one, 361 with two. That is more than one language's slice of 80 pages holds. **Owner decision:** pass on the point estimate with the interval reported, or grow each language's set until the bound clears.
  3. **Call 1 and section selection** carry the recall rule the fetch filters have: zero funding lines with an amount missed on the set.

  *Superseded 2026-10-03 by §5.5:* a fact kind that fails hides every award that needs it in that language, and the bounds are certified on the owner's gold set rather than on this model-built key. The Wilson decision in item 2 is settled the same way: the owner chose to check enough facts to certify the bound, not to pass on a point estimate.
- **Proof is measured too.** A wrong saved website is the most expensive mistake in Part B, and nothing above scores it. The key is organisations whose website Wikidata, ROR or EACEA already records, including the Vietnamese practice set (§4). P1–P3 run on them blind:
  - **wrong websites saved must be zero;**
  - coverage, meaning how many each proof reaches, is reported beside it.

  P1 and P2 are free. P3 costs at most 2 credits per organisation, so about 200 organisations cost under 400 credits.
- **Revised cost:** about 80 pages at about 2 cents each for the key reader and the referee (§7.1's rate), plus four Jev arms and one translation pass per non-English page. Add the §5.4 filter set (about $1) and the proof set (under $0.50). **About $3–5 in total**, against the $1.50–3 above.

### 7.1 The first measurement, 2026-09-27 — throwaway script, 15 pages

Run before any of this was built, on the design's questions as first written, with DeepSeek V4 Pro as the second reader and `gpt-5.6-sol` as the blind referee. Pages: Stipendium Hungaricum (two), Türkiye Bursları, DAAD EPOS, Chevening, GKS, MEXT, the Chinese Government Scholarship, three Erasmus Mundus programmes, ETH, Amsterdam, the Swedish Institute, and Azerbaijan's state programme.

- **Cost:** Jev 403,506 tokens ≈ **$0.017**, about 0.1 cents a page. DeepSeek $0.19, referee $0.12. The whole run: $0.32.
- **Amount facts, referee-decided disputes (Jev right / DeepSeek right):** who pays 19 / 11, covers 17 / 4, period 11 / 1, bound 9 / 4. Spot checks of agreed answers found none wrong. Estimated Jev accuracy: who pays ≈ 88%, covers ≈ 94%, period ≈ 98%, bound ≈ 94%.
- **Eligibility:** eligible 92% and excluded 97% agreement. **Dates:** month 100%, year 92%.
- **Two questions changed as a result** (§5): the holder question (80% agreement, shared errors) and "is it available" (0 of 8 disputes).
- **Two defects were the test's own, and are the lesson for candidate finders:** the date finder clipped "February 2027" to "February 20", so every "wrong day" was a wrong candidate; and the `who pays` list lacked `benefit_in_kind`.
- **Wording:** the two funding-line wordings flagged 274 and 562 lines; the two `who pays` wordings agreed on 91 of 95.
- **DeepSeek returned off-format answers** (a list where one value was asked) on several pages: the reason writing models stay away from structured facts.
- **A platform bug surfaced:** `reader.readable_text` garbles every non-ASCII page that carries no charset declaration, which Firecrawl's pages often lack; Azerbaijani, Turkish, Russian and CJK pages reach every model corrupted (§10). Fixed by PR #155 (095317f9), merged.

## 8. Cost summary

| | today | this design |
|---|---|---|
| reading one funding page | ≈ $0.35 | ≈ $0.01–0.02 with the slice-2 readers, half that on the batch-priced sweep, capped at $0.25 (§5); the Jev-only estimate was ≈ $0.002 |
| a student's first pack | ≈ $1–11 | ≈ $0.6–1 (search dominates) |
| building the EU catalogue | ≈ $13,000 | re-estimated after §7; expected well under $1,000, mostly search, less again with the eligibility pre-filter |
| measurement | none | the funding part ≈ $3–5 once (§7); the whole shared harness ≈ $4–7 (decision engine §9); ≈ 1¢ per audited page |

## 9. Failure handling

- **A vendor outage** means "not yet checked". Nothing is written off, and nothing is retried on a schedule.
- **A spent budget** means new checks wait. Students see what is already proven and read.
- **A value the serve rule cannot accept** (a split Opus's answer does not settle, or a quote that fails code's check) climbs the ladder (§5.5). Still unresolved at the top, the award goes to the hold queue, hidden; it is never shown as `not_stated`. A language below the bar shows nothing (§5.3).
- **A reader host outage** means "not yet read". A batch request that did not finish is missing, never an answer (§5).
- **Two students needing the same organisation** share one check (§4); the second waits for the first's result.
- **A spent platform budget** stops new catalogue checks. Students see what is already verified. A student's `wallet.py` cap never stops catalogue work.
- **A changed page** hides its award until re-verification passes (§5.5).
- **A monitoring alarm** (§5.5) hides the affected fact kind and language until it is re-certified.
- **A proof that goes stale** (§4) hides its cards until the website is proven again.
- **A Chinese-host refusal or omission** is redone on a non-Chinese host.
- **A quarantined page** (D8) yields no award.
- **A proof conflict** means neither organisation gets the website.

## 10. What this supersedes

- The resolver hold-out as the write gate (`2026-09-25-name-to-site-resolver` plan, Tasks 10–12). Vietnam becomes practice data.
- The "stop if depth 3 misses a kind word" rule.
- The funding judge's three readings and unanimity (`2026-09-14-funding-reader-precision-design.md`).
- Scheduled retries on this path. A *scheduled check* is not a retry: §5.5's freshness job is the one schedule, and it replaces the master design's monthly checks and the provenance-gate spec's "30 and 7 days before the deadline".
- "Not stated" as the display of an unsure value (§5 step 7). An unsure value now hides its award.
- **`2026-09-27-government-funding-discovery-design.md` and its plan 1** (branch `claude/gov-funding-discovery-design`) are folded into §3.1 and retired. Their human paths (`SITE_UNKNOWN`, `SAME_SCHEME`, Wikidata-only accounts as questions, special-category consultant tasks), the "being confirmed" card state, and the plan's edits to `funding_judge.py` (which engine plan 3 deletes) do not carry over.
- "A person decides" for resolver conflicts.
- Unanimity as what sets `FundingOpportunity.served`, and the operator queue `manage.py funding_review` as a reviewer of values (§5 step 7). The field and its reader `funding/pool.py` stay; only its writer changes. `funding_review` returns only as the hold queue, which fixes wording and never values (§5.5 step 6).
- **The 2026-10-05 serve rule** (Jev + Kimi K3, Sonnet 5.5 breaking ties), replaced on 2026-10-12 by DeepSeek V4.1 Flash + GPT-6-luna with Opus 5.5 on a split (§5.5).
- **Rows the three-reading judge already wrote** are not shown under the new rule. Each is re-read by the funding reader (§5) the first time a student needs its organisation, and the old row is replaced. No migration converts them, because their values came from a reader this design retires.
- `tests/research/test_vocabulary.py::test_the_committed_kinds_name_every_kind_v5_lacked`, which still fails on the gate branch ("embassy" and "commission" missing at depth 3). It encodes the retired "stop if depth 3 misses a word" rule. Plan 4 replaces it with the practice run's score (§4) rather than raising the depth to satisfy it.

**What governs, when documents disagree** (as of 2026-10-03):

| question | governing document |
|---|---|
| organisations and sources (Part A, including government funders at every level §3.1, social accounts, TOP-U v1 and the Azerbaijani lists), website proof, the funding reader's questions and finders, fetch filters, verification, freshness and the gold set (Part F) | this document |
| which model answers what, at what bar, on which host; the second reader; masking; the shared harness and its targets; the build order of plans 1–3 | `2026-10-03-one-decision-engine-design.md`. It supersedes §6.1, §6.3 and §7's pass bars here. **Except, since 2026-10-12:** the readers of the funding engine and its question sets (DeepSeek V4.1 Flash + GPT-6-luna, Opus 5.5 on a split, and the reader list as configuration) are the owner's decision recorded in §5 and §0.25. That document's second-reader choice does not apply to them. |
| letters and CVs: writer model, checks, hosts, censorship route | `2026-09-28-one-letter-engine-design.md` (§6.2) |
| Jev's question primitives, D8 injection screen, `decisions.py` | `2026-09-22-typed-decisions-and-multilingual-sources-design.md`, except where §5 here changes a question |
| the funding engine around the reader (search, packs, cards' fields) | `2026-09-22-funding-search-engine-master-design.md` |
| owner-labelled requirement corpus | `2026-09-23-labelled-corpus-design.md` (not replaced) |

**Defects that must land before any plan here, because every reader inherits them:**
- ~~`reader.readable_text` hands page bytes to lxml, which assumes Latin-1 when no charset is declared.~~ **Landed:** PR #155 (095317f9) decodes UTF-8 first.
- `funding_reader._FUNDING_TERMS` knows no Turkish, Azerbaijani or Russian funding words (burs, təqaüd, стипендия). Its only non-English words are `beca`, `bourse` and `borsa`, so it drops whole sections of the pages Azerbaijani students need. **Still owed.** The fix is the per-language table of §5 step 1, covering every destination language, not three words added to the regex.

Not superseded: four fixes prepared on the local branch `claude/resolver-gate-vn` still land, because they fix real defects.
- Firecrawl's `html` carries no `<head>`, so page titles were lost. `_with_head` restores them, and this was verified live on 3 pages.
- The Wikidata kinds query timed out on every run. It now uses `hint:optimizer "None"` and takes 2.4 seconds.
- The Diffbot fixture was captured live.
- The Diffbot terms re-read was recorded.

## 11. Build order: five plans, each its own implementation plan

**Who builds what** (agreed between the two design sessions and confirmed by the owner, 2026-10-03), so no two sessions implement the same code:

| builder | scope |
|---|---|
| decision-engine session (engine plans 1–3; plan file `docs/superpowers/plans/2026-10-03-engine-eval-harness.md` for plan 1) | the harness, key format, model-built key, Learn-then-Test bars and monitoring; **the owner's checking page** (PLATFORM_ADMIN-only, staff MFA, one platform-only table `GoldItem`: queue row, verdict ✓/✗/not_on_page and the typed fix, same RLS recipe as `research_resolutionitem`, no DELETE grant, kept forever; engine plan 1, commit e580c40b); the two model clients and masking; **the funding reader** in `apps/research` (Jev-only when written; the reader stack since 2026-10-12 is §5's, and the plan-3 session builds slice 2), implementing §5.2's questions and deleting `funding_judge.py`'s vote; the per-language funding-word table, because it sits in the reader's path |
| verified-catalogue session (this document) | Part B additions to `provenance.py::decide()`; Part A sources (§3, §3.1); the fetch filters F1–F3; Part F's non-model pieces: the show rule on `served`, the freshness job, "expected to open" and `funding_period` in `validity.py`, platform-budget charging. It consumes the certified bars (from `GoldItem` rows with `purpose=certification`) and does not compute them |

- **This document still governs the questions** (§5.2); the decision-engine session implements them.
- **Migrations** in `apps/research` and `apps/funding` land in plan order and are rebased onto whichever lands first; `makemigrations --check` is the gate.
- **`infra/template.yaml`:** the freshness job's EventBridge rule sits beside the mailbox session's rules (PRs #168, #170) and `ReminderLadderRule`. Whichever lands second rebases.

Plans 1–3 below are the decision engine's plans 1–3 (its §10), and that order governs. Plans 4–6 here are this document's own.

1. **Measurement (Part E).** Everything after is scored by it.
2. **Model routing (Part D):** identifier stripping and the funding side of routing. The letter checks and the letter and CV model trial follow the letter design (§6.2). TypeSafe's and OpenRouter's terms were accepted on 2026-10-03 (§6.4).
3. **The funding reader (Part C; readers per §5 since 2026-10-12; slice 2 scope in §5),** including D8 (step 0), the per-language term table (step 1), the regions rows (step 4), `target_level` and `funding_period`. **Part F's non-model pieces are this session's**, as a plan of their own after the reader: the show rule (step 7), the ladder's wiring, the freshness job, and "expected to open". The checking page and the improvement rounds come first (engine plan 1), because the certified bars come from them.
4. **Proof and registers-first discovery (Part B)**, as additions to the provenance gate's `decide()`, landing the `claude/resolver-gate-vn` fixes first. That branch sits on old master `df6fc3ca` and needs a rebase. Includes P3, the shared-host rule, the Facebook rule, the single-flight job (§4), the `phonenumbers` dependency and the stale-proof triggers.
5. **The eligibility pre-filter, national scholarship databases, the Azerbaijani lists, TOP-U v1, the pre-built core, and government funders at every level with social accounts (Part A, §3.1).** The core is verified before launch. The government answer key is built first, as §3.1's recall yardstick.
6. **The fetch filters F2 and F3 (§5.4)**, each shipped only after its recall measurement shows zero skipped awards. F1 ships with plan 5 under the same rule.

### 11.1 Gap audit of this session's build scope (2026-10-03)

Two read-only audits probed Part A, Part B, the filters and Part F's non-model pieces against `origin/master` (02926ac2). Reports: `scratchpad/gap-proof-verification.md` and `scratchpad/gap-sources-filters.md`. Three claims were re-checked by hand before writing them here:
- `GOVERNMENT_ZONES` lacks `gov.az` and `edu.az`;
- `wallet.charge` has no caller;
- `evaluation.py` has a human `POSSIBLY_ELIGIBLE_REVIEW` outcome.

**Settled after the audit:** U1, proving a university in a country with no readable register, is the lean rule of §4.1.

**Part B: proof (fixes to this document's design):**
- **P2 is new code, not a mapping.** `recognition.government_zone()` is a bare suffix match with no identity check. On master today, `yok.gov.tr` is accepted as *any* Turkish body's site. `GOVERNMENT_ZONES` lacks `gov.az`, `edu.az`, `gov.kz`, `gov.ge` and `gov.uk`, so `htp.edu.az` and `edu.gov.az` (the launch core) cannot be proven. Fix:
  - merge `GOVERNMENT_ZONES` with `domains.VERIFIED_SECOND_LEVEL` into one cited list;
  - add the site-identity check (title or `og:site_name` on the homepage) inside `government_zone`.
- **P1 is weaker than §4 says.** Register rows recognise a site with no fetch and no name check; only curated-list rows run `verify_origin`. A lapsed domain whose RDAP lookup *fails* comes back RECOGNISED. Fix:
  - register rows run `verify_origin` plus the name check;
  - a failed RDAP lookup is "unknown", never "not taken over".
- **Shared hosts are a schema change.** `www.gov.uk`, `europa.eu`, `diplo.de` and `usembassy.gov` are each one registrable domain. `OrganisationDomain` and `ProvenanceVerdict` key on the domain alone, and about 10 callers assume that (pool, sweep, vouch, `holder_domain`). Fix: a `path_prefix` column (empty for every existing row), a migration with an RLS re-check through `runtime_connection`, and every caller moved to (domain, prefix).
- **Social link proof has nothing to build on.** `facebook.com` is not a hosting platform, so one body could own all of Facebook. Vouching matches by domain, not by exact page, and nothing stores a site's outbound links. Fix:
  - add the social hosts to the hosting-platform list;
  - `SocialAccount` rows are written only from a proven site's outbound link, matched by exact account;
  - the serve gate (the decision-engine session's reader) accepts a post URL only when it matches a registered `SocialAccount` of the holder.
- **The gate is off by default.** `PROVENANCE_GATE_ENFORCED` defaults to "", and a counsellor can make an UNCONFIRMED body visible. Fix, per §0.18:
  - turn it on in production settings, pinned by a test;
  - `replace` refuses UNCONFIRMED;
  - `recognition_note` is never shown to a student.
- **The "check once" job is already built.** One verdict per domain, `_pending` and the pack sweep already give "two students, one check" and "still being checked". §4's new job row is dropped in favour of reusing them.
- **Proof re-checks:** universities are not re-checked on a schedule (owner, 2026-10-03; §4.1). Other bodies keep §4's evidence-only triggers.
- **P3 has no data yet:** `RegisterEntry` lacks registration number, address, phone, purpose and category. Adding them is safe. P3 ships once at least one adapter fills them.

**Part A: sources:**
- **The State Programme list is not ingested,** and its size differs by source. The provenance-gate spec records about **276 institutions and 2,907 master's rows for 2026/27**, from a 50-page PDF fetched as bytes through `fetch_data_file`; the breadth note says 221 and 4,405 for 2025-26. The size is read from the PDF each cycle and never hard-coded. It maps to **one award linked to many programmes** through the existing `FundingOpportunityProgram`.
- **Curated-list rows need a person to review them** (the provenance gate's curated path). Rows harvested automatically, such as a re-read of `htp.edu.az`, are admitted only by proof.
- **No government-directory source exists.** For Azerbaijan, gov.az's own domain register serves as the directory: it names the body holding each `.gov.az` domain.
- **The government answer key does not exist** on any branch. It is built first in the §3.1 plan.
- **Leiden Open is downloadable** (Zenodo record 17473224, CC0, checked live), as XLSX. Reading it needs an XLSX parser, a dependency decision for the TOP-U plan.
- **The "first student need" trigger does not exist** (no `run_tap` on any branch). The pre-built core is therefore a batch management command first, and the on-need trigger comes with Part F.
- **`htp.edu.az` publishes its calls under `/az/news/…`** (the Morocco programme at `/az/news/3413`, checked live), and `site.map_site`'s `EXCLUDE_PATHS` skips `/news`. For government bodies, news paths are kept.
- **Pointer names** come from `funding_judge`, the code being deleted. The funding reader (§5) must keep emitting them (sent to the session that builds it).
- **New tables need their seams:** `SchemeLink` is applied in `pool.candidate_pool`, and `EligibilityAnswer` is classified in `apps/audit/redaction.py`.

**Filters:**
- **F3 is not wired:** `map_site` has no production caller, and `_links` drops titles.
- **F1 has almost nothing to run on:** the only foundation register is `vgm_tr`. F1 ships last.
- **Who builds which measurement set:** the filter recall set belongs to the decision-engine session's plan 1. The **proof measurement set** (zero wrong websites) is not in it, so it is this session's.

**Part F: the non-model pieces, and what the decision-engine session must carry:**
- **The show rule's writer is the reader's `_served`,** in the decision-engine session's plan 3, as is the per-value "which readers agreed" record. The existing `unconfirmed` field shows a disputed value blanked with a caveat, which is the opposite of verified-only, so it is retired on the student path. This session owns `pool.py`: **PROGRAM-scope awards never reach the pool today** (it filters `scope_type="HOLDER"`), and that is fixed there.
- **Eligibility (`apps/funding/evaluation.py`, this session's).** It returns ELIGIBLE when a page says nothing about who can apply, it has the human `POSSIBLY_ELIGIBLE_REVIEW` outcome, and it lets UNVERIFIED cycles into the pool. All three are tightened to §5.5's rules behind a setting, then the setting is turned on.
- **Freshness is mostly built.** `validity.cycle_validity` already returns UPCOMING from past cycles, and ENDED from a register's `grant_window_end`, which `funding_period` should feed. `next_check()` already schedules re-checks, so §5.5's freshness table is implemented **in `next_check()`**, not as a new job. The daily `VerifyDueCyclesRule` ships DISABLED, for three reasons:
  - its two-model reader needs an Anthropic key, and **porting that reader belongs to the cycle verifier (slice 4)**, onto the §5 reader stack (it was written as a port to Jev);
  - its precision gate has never run;
  - an S3 grant is missing, which is this session's infra fix.
- **Reminders read `Application.deadline`,** which nothing fills from the catalogue, and `Application` links a programme, not an award. The reminder path runs per tenant with no catalogue access. Fix: the verified award deadline is written onto the application when the kit starts, and the pre-reminder check is **queued ahead of** the reminder rather than run inside it.

**This session's plan order, revised:**
1. Proof additions: one zone list with the identity check, P1 origin and name checks, the gate on with human paths removed, the per-student rate limit.
2. Shared-host schema (`path_prefix`).
3. The Azerbaijani core as a batch command: `htp.edu.az`, the State Programme PDF, the named schemes; plus the government answer key and the proof measurement set.
4. **Universities (§4.1):** the WHED reader, exact-name matching, the all-names identity check and the parent rule; then TOP-U, whose step 1 "national register floor" becomes "recognised under §4.1".
5. Part F's non-model pieces, after the reader lands: `evaluation.py`, `pool.py` scope, freshness in `next_check()`, the deadline bridge, the S3 grant.
6. The §3.1 routes: weekly gazettes, the receiving side, the pointer consumer, `SchemeLink`, the special-group card.
7. The social reader (a Browser Use client, plus `SocialAccount`/`SocialPost`).
8. Filters: F3, then F2, then F1.
9. **EMJMs as programmes (§3.2) and student-typed programmes (§3.3).**
   - Now: `body_names()` restricted to REGISTER and CURATED_LIST rows (the PR #173 follow-up; `plans/2026-10-05-emjm-title-not-a-name.md`).
   - After the card reader (plan 3): application routes (§3.4: the apply-page finder, `ApplicationSystem` seed, `ApplicationRoute`/`RouteStep`/`RouteDate`, their certification); the typed programme (§3.3: link or search-and-confirm, read and judged, 20 per student per paid cycle), and the EMJM reader with track rows, the consortium-site proof, and the self-funding and EMJM questions as read from the profile.

P3 joins plan 1 or 3, whichever first has an adapter that fills its columns.

## 12. Open risks

- **Verified-only trades coverage for trust.** Every unsure fact hides its award, so the visible catalogue starts smaller than the read one. The ladder and the improvement rounds are what grow it. The share of read awards that become visible is reported per language and per fact kind, so a shortfall is seen, not felt.
- **"Never" is a bound, not a proof.** At most 1 in 100 per shown field, deadlines included (§0.13), is what the gold set certifies at 95% confidence. *(The 2026-10-03 text said 1 in 1,000 for deadlines; §0.13 replaced it on 2026-10-09.)* The code checks, the reader pair with Opus on a split, the site hunt and the re-check before every reminder sit on top of it.
- **The owner's checks are the truth anchor.** About 30 hours before launch, then a few hundred facts per later change. An error in the owner's own labels moves the bound, which is why each item shows the official sentence in context.
- **Azerbaijani may not have enough funding pages for its own check.** Bars are pooled across languages and then checked per language. A language whose gold facts cannot meet the bound shows nothing. For Azerbaijani, the launch's own country, the State Programme list and htp.edu.az are the first pages to draw from.
- **Register rows can hold a person's address and phone** (§3). They are used only for matching, but they are stored, so they count as personal data for erasure and access requests.
- **TypeSafe added Nebius and CoreWeave as sub-processors on 2026-10-03** (§6.4). The terms are accepted. Whether to object within the 15-day window is the one live terms question for student text.
- **A filter that skips a real award is invisible by construction.** §5.4's zero-miss measurement and the 1-in-20 audit of skipped items are the only things that can see it; neither may be dropped to save credits.
- **Number and date finders in other scripts** (CJK units, local month names) need their own tests.
- **Registers differ by country.** Some list no websites and some cannot be downloaded, so each country is a small adapter of its own.
- **Owner questions carried from the government design (§3.1):**
  - Do bonded and forgivable money count? The design reads that they do.
  - Special-category conditions (disability, religion, refugee status, health) now hide the scheme; under no-human there is no consultant path.
  - ~~Browser Use's terms for the social reader.~~ Settled by the owner on 2026-09-24, on counsel's advice (master design, social hosts read through Browser Use).
- **IAU's consent for WHED** (2026-09-11) covers scraping and access, but does not name storage or commercial use. The platform stores one website and IAU ID per university, and the owner should confirm this with IAU.
- **The first student outside the pre-built core waits** while its organisations are proven, read and verified.
- **The hosting decision** is recorded as the owner's, with the GDPR point stated in §0.
