# The coverage-driven funding engine

**Status:** design approved in direction by the owner 2026-09-19 (coverage-driven engine over the
crawl-driven catalog; home country as a discovery dimension; tiered agreement; awards as their own
applications). This document is the written form for review before an implementation plan.

**Goal, in the owner's words:** find *all possible fundings* for a student, by the subcategories
already specified (the fifteen holder types of the funder-reader design §3.1), then filter by the
student's profile and desires.

Builds on, and supersedes where it says so: `2026-09-19-recommendation-spine-design.md` (becomes
Layer 5 of this design), `2026-09-18-funder-reader-fetch-tiers-and-resolution-queue-design.md`
(the fetch ladder §4 and cycle verification §3.5 are used as written), the organisation-register
plan of 2026-09-18, and `2026-09-17-role-routed-discovery-design.md` §4.13 (the search-provider
roster).

**Consolidation, 2026-09-19.** As of this revision, every discovery/funding-engine document lives
in one worktree (`git log`, this branch), merged from three lineages that had diverged since
2026-09-14 with almost no file overlap: `claude/program-page-reader` (the spec trunk — this
document, the funder spec, the register plan), `claude/programme-funding-reader` →
`claude/reader-holder-axis` (the reader implementation — holder axis, `validity.py`, this and the
spine spec), and `claude/vendor-fetch-path` (the fetch ladder implementation, `vendors.py`). The
merge was code-only (three-way git merge of committed history, no working-tree changes taken from
any session's in-progress checkout) and is proven by the full suite: 2,825 passed, 0 failed,
lint and mypy clean, `makemigrations --check` clean after one migration renumbering
(`0031_snapshot_fetched_via` → `0037`, whose `dependencies` pointed at a name — `0030_cv_directives_undecided_unreadable`
— that had since been renumbered upstream; see CLAUDE.md's own "Migrations" section for why this
exact collision shape is expected and not itself a bug).

### Where each nuance lives — status as of the merge

| document | owns | status |
|---|---|---|
| this document | the cell space, three enumeration engines, tiered agreement, award identity, channels, the scheduler | **spec only** — none of Layers 0/1/3(new fields)/4 is built |
| `2026-09-19-recommendation-spine-design.md` | Layer 5: pool → gates → pack; awards as their own applications | **spec only** — no `facts.py`, `pool.py`; `cycle_validity` not wired into any hard gate |
| `2026-09-18-funder-reader-fetch-tiers-and-resolution-queue-design.md` | §3 holder axis; §3.5 cycle verification decisions; §4 fetch tiers; §5 the resolution queue (C) | **§3 built** (holder axis, this worktree's reader-holder-axis history); **§3.5's pure validity function built** (`apps/funding/validity.py`), its evidence ladder (crawl/Wayback/register cadence) **not built**; **§4 built** (`apps/research/vendors.py`, `fetch_ladder`); **§5 (C) not built** — `ConsultantResearchTask` is the pre-existing generic escalation, not a resolution queue |
| `2026-09-18-organisation-register-and-provider-protocol.md` (plan) | the `Organisation` register, provider adapters (Exa/Brave/Tavily) | **not built** — only Task 1 (`apps/research/hosts.py::registrable_domain`) exists, built identically on the reader-holder-axis lineage so it merges without conflict |
| `2026-09-18-funding-reader-holder-axis.md` (plan) | the holder axis, pointers-as-leads, tiered reading, cycle fields | **Tasks 1–8 built**; Task 9's pure function built, its ladder not; **Task 10 (truth set, gate) not built** |
| `2026-09-19-vendor-fetch-path-and-deletion.md` (plan) | the vendor fetch ladder; deleting the Scrapling/browser tier | **the fetch ladder built** (`vendors.py`); **the deletion not executed** — `browser_server.py` still present, dormant at `BrowserDesiredCount: 0` as the plan itself specifies until then |
| `2026-09-17-role-routed-discovery-design.md` | the search-provider roster (§4.13), what was rejected and why | **not built** — no `apps/research/providers/`, no Exa/Brave adapter |
| `2026-09-14-emjm-partner-source-design.md`, Korea (`2026-08-28-funding-led-discovery-design.md`) | the EACEA project API, data.go.kr | **not built** (each spec says so itself) — the pipeline still harvests only the HTML catalogues |
| `2026-09-13-institution-programme-funding-search-design.md`, `2026-09-14-funding-reader-precision-design.md` | the original programme-funding reader (three readings, quote verification, disputed fields) | **built** — this is the reader the holder axis extends |

### Recommended build order, given the above

Groundwork first, cheapest-to-verify first, and nothing that duplicates a peer session's live work:

1. **The Organisation register** (register plan Tasks 1–11) — nothing else in Layer 1 has anywhere
   to put a body once found. Task 1 already exists; start at Task 2.
2. **The eligibility-key vocabulary and its writer** (this spec §6.1; funder spec §3.1's promised
   vocabulary) — closes the gap the spine spec flags as blocking most of Layer 5, and gives
   `BenefitRule` its first writer.
3. **The translation layer and the wired hard gate** (spine spec §5.1–5.3, the owner's original
   ask) — now buildable against real eligibility triples instead of shape-only nationality data.
4. **Tiered agreement + award identity** in `funding_judge.py`/`funding_reader.py` (this spec §6.2–6.3)
   — the fix for "ten awards decided, none shown".
5. **Closed-list engine** (this spec §4.1) for the launch countries.
6. **ROR gate → register engine** (this spec §4.2), then channels gate (§4.4).
7. **The cycle-verification ladder** (funder spec §3.5.2) and **the resolution queue** (funder spec
   §5) — largest remaining pieces, last because everything above makes their inputs richer.

## 1. Why this exists

The engine as built can find money and can score options, and it has two blindnesses that no
amount of running it removes:

1. **It cannot say what it has not found.** Discovery is crawl-driven: seeds and search produce
   pages, pages produce awards, and nothing represents the *space* of funding. "We found 12" and
   "there are 12" are indistinguishable. The repository already knows the cure for this — the
   register model stores `RegisterCoverage` precisely because an absence only means something when
   the denominator is known — and never applied it to funding.
2. **It knows only the destination.** A `DiscoveryQuery` is field, country and level. Money lives
   in three geographies — the **host** country, the **home** country (a state programme for its
   own citizens abroad, home-government loans, diaspora foundations), and **neither** (EU, UN,
   development banks, embassy pairs) — and two of the three are invisible to a destination-keyed
   engine, for every student.

Two more limits are downstream of those and were measured on 2026-09-19: the reader's decided
fields are how you apply and what form the money takes, while what filtering needs — *who* is
eligible — is stored only as a shape ("a country list") and never as content; and one
disagreement between the model families on any decided field hides the award, which is the wrong
failure direction for a recall-first goal (ten awards decided on five known funders, none shown,
all split on `route` and `money_form`, none on `holder`).

## 2. Principles the design rests on

- **The catalog is about the world; the pack is about a person.** World facts are gathered once,
  cost money, and are shared by every tenant; the per-student filter is cheap and private.
  Nothing personal enters the catalog path.
- **Know the denominator.** Every count of found things is reported against the size of the space
  it was found in — exact where the space is closed, estimated where it is open, and labelled.
- **The origin is the only evidence.** Aggregators, channels, tips and registers yield *names* and
  *timing*; evidence is a verbatim sentence fetched from the body's own site. Unchanged from
  CLAUDE.md, and the reason a tip-off channel can be watched without ever being cited.
- **Three values, never two.** An eligibility condition is satisfied, failed, or undecidable; an
  award's cycle is open, upcoming, or unverified. Passing silently what cannot be decided offers a
  shut route; failing it silently hides an open one.
- **Measure before adopting.** A source, vendor or knob enters a plan after a holds-and-generalises
  check against lists we already hold (owner rule 2026-09-18). This document names the check for
  each new element rather than asserting the element works.
- **Nothing names a scheme, funder, country or channel in code.** Lists, cells, cadences and
  terms postures are data rows with a source URL and a verified-on date.

## 3. Layer 0 — the funding space

A **cell** is `holder type × host country × home country × level`. Countries are ISO 3166-1
alpha-2 or `ANY`; level is `MASTER` until a second level exists. Cells are rows, never code.

- A **body** (a funder, an institution, a lab) sits in the cells its awards can fund.
- An **award** sits in one or more cells: a home-government scholarship for study anywhere is
  `(NATIONAL_GOVERNMENT, ANY, home, MASTER)`; a Land's stipend is `(SUBNATIONAL_GOVERNMENT, host, ANY, MASTER)`.
- A **student** selects cells from their profile: every holder type × their allowed hosts × their
  nationality (and residence, where a scheme keys on it) × their level.

The home axis is the one with the highest reuse. An agency's students share a home country, so
that country's ministry, its embassies abroad, its loan schemes and its diaspora foundations are
enumerated once and serve every student the tenant ever has.

## 4. Layer 1 — enumerating the bodies

The fifteen subcategories fall into three kinds of universe, and each kind gets its own engine.
The assignment is data: a subcategory can move engines per country when a country turns out to
publish a list nobody expected.

| subcategory | universe | engine | "all bodies" achievable? |
|---|---|---|---|
| National government | closed — a few agencies per country | closed-list | yes, checkable |
| Intergovernmental | closed — EU/EACEA, UN agencies, development banks, IsDB, OIC, Turkic Council, Commonwealth… | closed-list | yes |
| Regional fund | closed — Visegrad, Nordic Council… | closed-list | yes |
| Embassy / bilateral | closed — one per home×host pair | closed-list (derived from the pair) | yes; one read per pair |
| Political foundation | closed where the type exists (Germany's 13, published by the federal ministry) | closed-list | yes |
| Subnational government | closed — a country's regions are a finite administrative list | closed-list | bodies yes; each still read |
| Institution | closed — the registers already ingested | closed-list (WHED / DEQAR) | bodies yes; each still read |
| Alumni | attached to institutions | derived from the institution list | bodies yes |
| Professional body | mostly closed — chambers, learned societies per field | register (ROR, professional registers) | mostly |
| Bank / lender | mostly closed — national loan schemes; banks finite | closed-list + register | mostly |
| Religious | mixed — inside the closed lists in some countries, diffuse elsewhere | closed-list + register + open-tail | partly |
| Private foundation | **open long tail** | register (ROR `funder`; national foundation registers) + open-tail | no — **estimated** |
| Diaspora / affinity | open, keyed to the home country | open-tail on the home axis + register | estimated |
| Employer | **open and unbounded** | open-tail | estimated |
| Unstated | not a subcategory to enumerate | — | — |

So ten of fourteen enumerable subcategories can reach a *checkable* "we have every body"; the four
open ones get a *number* instead of silence (§9).

### 4.1 The closed-list engine

One sourced row per list: the URL that publishes it, the date it was verified, the country and
subcategory it covers, and the bodies it names. The shape is `registers.py`'s "one frozen config
per register", extended from institutions to every closed subcategory. Completeness is bodies
known ÷ list size, and a list past its verified-on date raises re-check priority exactly as a
stale register cadence does (funder spec §3.5.1).

### 4.2 The register engine

Large authoritative datasets that enumerate bodies and say nothing about awards:

- **ROR**, filtered to `funder`, `facility`, `nonprofit`, `government`, `company`. Measured
  2026-09-19 (`docs/research/2026-09-19-dual-seed-review.md`): it carries a `funder` type and
  returned Cusanuswerk, Türk Eğitim Vakfı, Studienstiftung, Visegrad Fund, DAAD and the
  Baden-Württemberg Stiftung with their websites — four of them hosts from the list the yield run
  read. Two defects bound its use: the fuzzy top hit is sometimes a different organisation
  (Anadolu Vakfı returned Türk Eğitim Vakfı), so ROR is a lookup **with verification**, never
  "take the first row"; and ROR gives the organisation's site where we may hold the programme's
  (`bwstiftung.de` against `bw-stipendium.de`), so a binding is organisation → **domains**, plural.
- **National foundation registers** where they exist (a country's public register of foundations
  or charities), and **professional-body registers**, added per country as data.

Completeness is register coverage with a known denominator, as `RegisterCoverage` records it
today. ROR's second job, and the larger one: for any organisation it knows, name→site resolution
becomes a local lookup instead of the paid search call the resolver measurements spent five
versions on.

**Gate before ROR enters a plan:** run it against the 58 yield hosts and the pointer names the
funder path now produces; record the share of hosts ROR knows, the share with an *exact* name
match, and the share whose ROR website matches the domain we already hold. Free, no key.

### 4.3 The open-tail engine

Where no list exists: pointers off every page read (built 2026-09-18 — one Turkish page named 31
funders that were previously discarded), the search providers as the §4.13 roster assigns them,
and the channels of §4.4. Every name goes through resolve → read on the origin → verify; nothing a
third party said is ever evidence.

**A human channel is a source here, not a bypass.** A counsellor's tip, an alumnus's mention, a
professor's grant with a spare stipend — money that is not on the web — enters as a name and takes
the same path. This is the only route to that money and it deserves a first-class input, not an
afterthought.

**Rule written in, not hoped for:** a closed list is a floor, never a ceiling. The open-tail
engine runs in every cell regardless of how complete the closed list looks, because the thing a
closed list cannot see is the body that does not belong on any list.

### 4.4 Channels and feeds — tip-offs and timing, never evidence

Opportunity feeds exist at every scale: a ministry's announcements page with an RSS or sitemap
`lastmod`; a national aggregator; and, disproportionately in the launch countries, **Telegram
channels, mailing lists and Facebook groups** that post scholarships for one nation's students in
its own language. The repository already framed the question (`PROMPT-new-opportunity-surfaces.md`)
and never ran it; its framing is adopted here word for word where it matters.

What a channel may contribute, and what it may not:

| contribution | allowed? | why |
|---|---|---|
| a body's or scheme's **name**, and a **URL it links to** | yes — a name for the open-tail engine | the decisive test from the research prompt: *a post that links to the official source is usable as a tip-off; a post that only paraphrases is not* |
| **timing** — "applications opened", "deadline extended", a dated announcement | yes — as a **trigger** for re-verification of the cell it names, never as a cycle fact | *a surface that carries the news three weeks before the official website is worth watching even if it can never be cited*; a trigger costs one change-tracked fetch of the origin |
| an eligibility claim, an amount, a deadline | **never** | third-party paraphrase; the origin is the only evidence |
| anything about a person — commenters, forwarders, subscriber lists | **never retained** | privacy; the ingest keeps organisation names and links, discards the rest |

How they enter: as **feed sources**, one adapter per transport (RSS/Atom, sitemap `lastmod`,
Telegram's official API for public channels, a mailing-list archive), and one *row* per channel —
country, language, operator kind, subcategories it covers, machine-readable route, **terms
posture**, verified-on date. The terms posture is the same per-source discipline the portal work
used: a channel whose terms cannot be established is not read, and becomes a task for a person.
Telegram specifically: public channels only, through the official API, never a scraped web view
and never a user account impersonating a member.

Why they are worth the adapter, beyond direct yield: a human-curated channel is the most
**independent** route the engine has, which makes it the best second route for the recall estimate
in §9 — and it is the route most likely to carry a home-country scheme first.

**Gate before channels enter a plan:** run `PROMPT-new-opportunity-surfaces.md` Parts A–C for two
launch countries. Two numbers decide it: the share of names a channel yields that no other route
found, and the median lead time of a channel post over the origin's own announcement. A channel
that yields nothing new and leads by nothing is noise with a terms risk attached.

### 4.5 One organisation register

Every body, whatever engine found it, lands in the register the 2026-09-18 plan defines
(`Organisation`, keyed by registrable domain — `apps/research/hosts.py`), with the ROR lesson
applied: one organisation, several domains. The register carries, per body: which engines
enumerated it, its cells, its read state (§5), and its cadence rows (funder spec §3.5.1).

## 5. Layer 2 — reading a body

Reading is uniform whatever engine found the body, and it is **vendor-only**, as decided
2026-09-18 and measured end to end on 2026-09-19 (funder spec §4.0a, 58 hosts). **Built the same
day** (`apps/research/vendors.py`, merged into this worktree from `claude/vendor-fetch-path`):
`discovery.retrieve_official_source` tries our own client first (free; europa.eu always, and 49
of 58 hosts generally), then hands a refusal or a JavaScript shell to `fetch_via_vendors`, which
runs one of two orders chosen by `FETCH_VENDOR_MODE`:

| mode | order | when |
|---|---|---|
| `quota` (default) | scrape.do datacenter → scrape.do residential+browser → Firecrawl | both accounts sit on free credits |
| `paid` | Firecrawl (`proxy: "auto"`, free `changeTracking`) → scrape.do residential+browser | once a Firecrawl plan is bought |

**This inverts the design's original recommendation (Firecrawl first), on a cost basis this
design accepts:** scrape.do is 7x cheaper per credit, so its escalated 25-credit tier
($0.0029) is under 1% of the $0.35 reader run that follows it — dollars decide, never credits.
What must survive the inversion, and does: a scrape.do datacenter fetch executes no JavaScript,
so a body that fails `looks_unrendered` is **escalated, never returned as a read** — a shell read
as "this body states no funding" was 5 of 15 pages, 2026-09-19, and that failure mode is closed
by code, not by which vendor runs first. `render`/`super` (residential) stay **off first, on per
host recorded as needing it** — the anti-bot case that actually needs a residential proxy was 1
host in 58 — and every rung's `Scrape.do-Request-Cost` header is recorded per host in
`HostFetchCost`, never a tariff copied into settings; a `SweepBudget` stops a sweep at its
per-vendor dollar cap and `manage.py fetch_ladder` prints the bill. Tavily Extract remains the
fallback extractor as decided 2026-09-18. `europa.eu` never reaches a vendor
(`vendors.never_vendored`, tested) — student PII rides the pinned-address client, always.

A host that fails every tier with a network-class error is `UNREACHABLE`: retried three times
over seven days, then queued to a person if it is a plausible funder.

So the JavaScript shells that were a fifth of the positive-control sample (5 of 15 pages,
2026-09-19) are a *rendered page* once escalated and a *counted residue* only after every tier
fails — login walls and dead sites — never a silent "this body states no funding".

**No fetch vendor is ever pointed at a portal.** CLAUDE.md's "do not adopt rotating or
residential pools" protects the portal path, where the agent acts as an authenticated applicant;
a research fetch made by a vendor from the vendor's own address, of a public page, is the
vendor's egress, not ours — the reconciliation the funder spec §4.1a records.

**The output of a read is per organisation, not per page:** *read completely on date X, N pages,
M unreadable, at tiers T*. That gives the engine a state it never had — **known but unread** —
and the state matters at scale: fifty home countries × fifty hosts is 2,500 embassy pairs, and
the engine reads the pairs students actually select, knowing exactly which it has not. This
per-organisation rollup is **not yet built**: `vendors.py` and `fetch_ladder` record per-host
cost and tier; nothing yet aggregates that to an organisation's read state.

## 6. Layer 3 — extraction

Three readings, two model families, every stored sentence verbatim from the page — unchanged.
What changes is what is primary, how disagreement is handled, and what an award *is*.

### 6.1 Re-centred on eligibility

Primary outputs, in this order:

1. **Existence** — offered, holder, name, benefit form and amount where stated.
2. **Eligibility conditions as structured triples** — `key`, `operator`, `value`, and the
   sentence — in **one closed vocabulary shared by awards and programmes**: citizenship,
   residence, descent, region, affinity, need, gender, refugee or displaced status, disability,
   talent, field, level, age, prior institution, employment, language, work experience, and
   `UNSTATED`. This is the eligibility-key vocabulary the funder spec §3.1 promised and nothing
   implemented; it is also what gives `BenefitRule` its first writer. **Made concrete in
   `2026-09-19-eligibility-vocabulary-and-register-amendment-design.md`** — the closed key list
   with value forms, operators and deciders; two names there differ from this prose on purpose
   (`REGION` is a value form, `LEVEL` is `PRIOR_DEGREE`), and that document is authoritative.
3. **Cycle facts** — intake as written, date stated, deadline per condition (funder spec §3.5.3).
4. **Details** — how to apply, money form, coverage.

A programme page yields the same triples for its admission conditions, so the per-student filter
(Layer 5) evaluates one vocabulary against one profile for both kinds of thing.

### 6.2 Tiered agreement

- **Existence fields gate whether an award is shown at all.** "Never show money the page does not
  offer" is untouched.
- **A disputed detail or condition makes that field undecided, not the award.** The award is
  shown; the field reads *unconfirmed*; the filter never filters on it and it falls to the
  undecidable branch of the three-valued outcome for that condition — which is a consultant's
  task, not a hidden award.

This is the `route`/`money_form` decision the 2026-09-19 gate surfaced, answered without weakening
the guarantee that matters. The serve-rule constraint in the holder-axis plan ("the served rule
does not weaken") is amended to exactly this: it does not weaken on *existence*.

### 6.3 What an award is — a correction

The holder-axis plan keyed a holder award on `(holder domain, kind)`, so every page of one
foundation reaches one row per kind. For a foundation with one scholarship that is right. For a
ministry or an agency with dozens it **collapses distinct awards into one row** — a "find all"
engine that cannot count DAAD's programmes is not finding all. The correction: an award's identity
is `(organisation, page, the heading the quote sits under, kind)`. The page and the heading are the
site's own structure, stable across reads and not a model's choice; the judge's six-word `name`
remains a label. A list page that names many awards is a *directory*, and the pointer route
already treats it as one.

## 7. Layer 4 — verification and the scheduler

`cycle_validity` (`apps/funding/validity.py`, built 2026-09-19) with the full evidence ladder of
funder spec §3.5.2, every rung through the vendor: own pages, the site's own archive by crawl,
Wayback captures, the register cadence, one search. Only `OPEN` and `UPCOMING` reach the pack;
the interim rule from the spine spec (hide only what is known shut while the ladder is unbuilt)
retires the day the ladder lands.

The scheduler decides what is read next from three signals: **student demand** (cells selected
by live profiles), **cell thinness** (bodies known but unread, or open cells with a high unseen
estimate), and **announcement season** (a month before a cadence's opening; a channel trigger
from §4.4). Nothing unchanged is re-read: change tracking on every page, prompt caching on every
reading.

## 8. Layer 5 — per student

The recommendation-spine design, amended: the pool query is **cell selection** — the student's
holder types × allowed hosts × nationality and residence × level — instead of field and country;
programme applications and award applications are separate lists with their own deadlines; awards
are not counted as coverage of a programme's cost; three-valued gates; desires rank. The coverage
line is truthful and comes from Layer 0: *"N found in your cells; K cells still thin — researching."*

## 9. What every layer reports — recall gets a number

Per cell, stored and printed by the sweep:

| number | meaning |
|---|---|
| bodies known ÷ list size | closed subcategories: how complete enumeration is, exactly |
| estimated unseen | open subcategories: two independent routes on the same cell — how many bodies *both* found against how many only one found gives the standard capture–recapture estimate of how many *neither* found. Indicative, not exact: routes are never perfectly independent, so the estimate is a floor on the gap, and it is labelled as one |
| bodies read ÷ bodies known | the known-but-unread backlog |
| awards shown ÷ awards found | what tiered agreement and verification withhold, and why |
| cost per verified award | Firecrawl credits × plan rate, scrape.do's cost header, model tokens at list price, provider `costDollars` — recorded, never estimated |

Recall = bodies found × awards read per body × awards agreed. The first term is exact or
estimated per cell; the second is the read state; the third is the tiered-agreement report. None
of the three is a feeling.

## 10. Order of work

Groundwork first, and it is the part that makes every later number mean something:

1. **Layer 0 and the closed-list engine** for the launch countries' home and host axes, with the
   organisation register (domains plural) and the read state. Gate: the closed subcategories of
   two countries at 100% enumerated, read states recorded.
2. **ROR gate** (§4.2) → register engine → resolver's first stop.
3. **Extraction re-centred** (§6.1) with tiered agreement (§6.2) and award identity (§6.3);
   `BenefitRule` gains its writer. Gate: the 58-host re-run's `awards shown ÷ found`, and a
   hand-check of 30 condition triples against their sentences.
4. **The spine as Layer 5** (its own spec, amended).
5. **Channels gate** (§4.4) → feed adapters → scheduler triggers.
6. **The verification ladder** (funder spec §3.5) once the vendor client exists; the interim
   validity rule retires.

## 11. Deliberately not built

A live per-student search with no shared catalog (every student pays full cost, nothing is
reused, completeness is never knowable, two identical students get different money on a provider
hiccup). Diffbot as an enumerator (measured 28% precision, 2026-09-18). A single generic
"applicable thing" protocol over programmes and awards (a gate that silently skips a field is the
failure mode this repository treats as worse than a crash — the shared *condition* engine gives
the reuse without it). Any new UI.

## 12. Open for the owner

- The cell's home axis keys on nationality; some schemes key on **residence** or **descent**
  instead. The vocabulary of §6.1 carries all three. The profile already collects nationality and
  `country_of_residence` (`StudentProfileSnapshot`), so the pool selects on both today; **descent is
  not collected**, so a descent-keyed award (AGBU's "of Armenian descent") can only ever reach the
  undecidable branch until the consultation asks for it. Whether to ask is a product decision.
- Telegram's official API for public channels needs an application credential; whether the
  platform holds one is an operational question, not a design one — but it gates §4.4.
