# The reader learns who holds the money; fetching gets tiers; abstentions get an owner

Builds on `2026-09-17-role-routed-discovery-design.md` (discovery, register, resolver; §4.13c is
the measurement this design answers) and on the funding reader in
`2026-09-14-funding-reader-precision-design.md` (branch `claude/programme-funding-reader`).
Owner decisions 2026-09-18: A, B, C below approved; the same evening B was rewritten to a single
vendor fetch path — Firecrawl at full capability, Tavily Extract as fallback, Scrapling retired (§4).

## 1. Why this exists

Page-level yield was measured on 2026-09-18: the funding reader, unmodified, over 58 hosts that
discovery produced for five countries — **2 awards served, neither from a funder**; every
foundation read served nothing, and the richest scholarship pages produced the most *pointers*.
The cause is not reading quality. The reader's award kinds are seven institution-side families and
its scope vocabulary ends in `POINTER` — "money a student gets by applying elsewhere" — which is
exactly what a foundation's own scholarship page is under that menu. The reader was designed for
programme pages, where a funder is somewhere else; on a funder's own page the same rule is wrong.
So today **discovering a funder cannot produce a card.**

The full family list was never lost: `FundingFamily` (eleven values, including
`PRIVATE_FOUNDATION`, `GOVERNMENT_SCHOLARSHIP`, `INDUSTRIAL_SPONSORSHIP`, `AFFINITY_OR_DIASPORA`)
and `FundingFamilyClaim` both carry it. The reader needs a second axis, not a recovered table.

Two more things the same day showed. **Eight of 58 hosts were refused by our own egress** — three
bot-blocks, two that a browser-like request reads, one server error, one broken TLS chain (Georgia's
education ministry), one timeout. And the engine now abstains honestly in four places — unknown
site, disputed award, unreachable host, one-token name — with no owner for the abstention: a
blocked fetch writes a `ConsultantResearchTask` that no screen lists; nothing writes one for the
other three.

## 2. Scope

Three components, one measurement gate each:

- **A.** A *holder* axis in the funding reader and a serve rule that serves an award on its
  holder's own page. Pointers become leads.
- **B.** One vendor fetch path — Firecrawl used to the full (scrape, crawl, map, change tracking, a
  measured cheap first read), Tavily Extract as the fallback vendor — and a retry queue for the
  unreachable.
- **C.** One resolution queue on the counsellor dashboard: precise asks, one-click answers,
  permanent write-back to the shared catalog, and an automation ladder that runs before anything
  is queued.

**Not in scope:** the option card's amount/deadline fields (increment 6 of the discovery design);
the classifier (§4.7 there — C.4 below consumes it when it exists); any portal automation (retired
by the glass-box design; the student presses Submit in their own browser).

## 3. A — the holder axis

### 3.1 Three labels per award

| label | values | source |
|---|---|---|
| **holder** — who owns the money | `NATIONAL_GOVERNMENT` (ministry, agency: DAAD, YTB, Chevening) · `SUBNATIONAL_GOVERNMENT` (Land, region, municipality) · `POLITICAL_FOUNDATION` (Germany's Begabtenförderungswerke: KAS, FES, Böll, Naumann…) · `RELIGIOUS` (Cusanuswerk, Villigst, Avicenna) · `PRIVATE_FOUNDATION` (Krupp, Zeiss, Anadolu Vakfı) · `EMPLOYER` (Siemens Stiftung; the Turkish central bank funding its own staff) · `INTERGOVERNMENTAL` (EU/EACEA, UN agencies, World Bank, IsDB, Turkic Council) · `REGIONAL_FUND` (Visegrad Fund, Nordic Council) · `EMBASSY_BILATERAL` (Fulbright, embassy tracks) · `DIASPORA_AFFINITY` (Heydar Aliyev Foundation, AGBU) · `PROFESSIONAL_BODY` (chambers, unions, learned societies) · `BANK_OR_LENDER` (loan schemes) · `ALUMNI` · `INSTITUTION` (the university or programme itself) · `UNSTATED` | new; closed literal in `funding_judge` |
| **family** | the eleven `FundingFamily` values | existing |
| **eligibility keys** | §4.9's set: `CITIZENSHIP / RESIDENCE / DESCENT / REGION / AFFINITY / OPEN / NEED / GENDER / REFUGEE_OR_DISPLACED / DISABILITY / TALENT / FIELD / AGE / PRIOR_INSTITUTION / EMPLOYMENT / UNSTATED` | **superseded 2026-09-19**: no such vocabulary existed in code (four partial ones did); the closed list, value forms and deciders are `2026-09-19-eligibility-vocabulary-and-register-amendment-design.md` §2 — `REGION` is a value form there, `LEVEL` is `PRIOR_DEGREE` |
| **timing** — when the student can apply for it | `PRE_ARRIVAL` (countable towards a visa's proof of funds) · `POST_ARRIVAL` (only after arrival and local registration — Germany's municipal stipends, France's CAF) · `EITHER` · `UNSTATED` | new; **increment 6, with amount and deadline — not in plan 1**. External review 2026-09-18; the card definition is §4.10 of the discovery design |

The list of holders comes from the repo's own research (landscape §2's route table, the outbound
synthesis's TCMB finding, the nationality-keyed synthesis's multilateral scaffold) and the owner's
2026-09-18 list; it is closed, and a page naming a holder no value fits is `UNSTATED` with the quote
kept — shown, never dropped.

**Out, owner decision 2026-09-18:** essay prizes, hackathon and competition awards. Money that
does not fund a master's is not an award here, whoever holds it. Same rule as mobility money.

### 3.2 The serve rule that changes

`scope` gains one value: **`HOLDER_OWN`** — the page's owner is the award's holder. The judge
decides it from the page itself (the organisation the page belongs to, from `Organisation` when
the host is registered, from title/`og:site_name` otherwise) against the holder the sentence names.
An award with `scope=HOLDER_OWN`, `offered=YES` and a stated money form is **served** exactly as an
`I1`–`I7` institution award is. `POINTER` keeps its meaning — a third party's money mentioned on
this page — and is no longer discarded: **every pointer becomes a `ResearchLead` into the
`Organisation` register** with `found_via=POINTER:<host>`, resolved like any other name
(2026-09-17 §4.13a/b rules). One Turkish page named 31 funders; that is a discovery route the
reader was throwing away.

`kind` for a `HOLDER_OWN` award is the family; `I1`–`I7` stay the institution-side sub-kinds. The
three-reading agreement, the quote verification and the disputed-field record are unchanged.

### 3.3 The disagreement rule (owner decision)

A **third reading breaks ties on `offered` only** — the one field where the 09-16 run showed the
two families splitting 17 times on whether a page offers funding at all. Every other disagreement
(kind, route, money form, nationality shape) goes to the queue (C.2) with the disputed fields named.
Cost: one extra call on the minority of chunks where the first three split on `offered`.

### 3.4 Gate

**Re-run the 58 hosts of 2026-09-18 with nothing changed but the reader.** Same pages, same
selection, same serve gate. The number that proves A is served awards on the foundation hosts that
produced pointers (Cusanuswerk 10, SBB 18, Anadolu, Abdi İbrahim, Begabtenstiftung Informatik,
bw-stipendium, Carina). Then a **positive control**: five pages known to carry awards (DAAD, TEV,
Cusanuswerk's programme page, Visegrad Fund, a Land scholarship page) — if any serves nothing, the
holder axis is incomplete, not the page.

### 3.5 Cycle verification — a student sees only awards the system has verified for their intake (owner decisions 2026-09-18, evening)

**The requirement, in the owner's words:** *the system should be so robust that it verifies by its
own and gives only the scholarships that are verified for a cycle.* No counsellor in this loop. An
award a page still describes is not thereby open; the ChEMoinformatics+ grants page — "about 20
Erasmus Mundus scholarships", and above it, dated 15/10/2025, *"the recruitment of the student
intake for the academic year 2026-2028 will be without scholarship"* — is the case that surfaced it,
and one row of the test set, not the rule.

**What the reader does today — traced in `funding_judge.awards`, not guessed.** The scholarship
lines agree as `offered: YES` and are **served**; the disclaimer is a *negation*, counted and never
joined to any award; a re-read that finds no `YES` writes no decision, so the row stays served; and
§4.8 of the discovery design attaches `I5` to every EMJM from the register alone.

#### 3.5.1 What "verified" means — open now, or verified to recur for the student's intake

The student's question is not "can I apply today?" but "will this money exist for my intake, and
when do I act?" A scheme whose window runs March–May for a September start must appear in a pack
built the previous September — as a dated plan, not as "apply now" (owner's case, 2026-09-18). So
verification has **two positive answers**, both resting only on the organisation's own pages or the
one application page they link to:

**`OPEN`** — (1) the award is `AGREED`, `offered: YES`, with a stated money form or benefit (the
serve rule); (2) a **dated** statement inside the current cycle window — the twelve months before
the intake starts — names the intake as open (`"Applications for 2026/27 are open"`, `"Call 2026
published 12 May 2026"`), **or** a stated deadline lies in the future and before the intake starts;
(3) no later-dated statement contradicts it for that intake.

**`UPCOMING`** — the window for the student's intake has not opened yet, and the scheme is
**verified to recur**: (1) as above; (2) **recurrence evidence** — at least two consecutive past
cycles with dated calls on the organisation's own pages (its news or call archive, or the same call
page as the Wayback Machine captured it in earlier years), or the page itself stating the scheme
runs every year and naming the month; (3) the **projected window** — the same months as the last
observed cycle — falls before the student's intake starts; (4) no dated statement of suspension,
discontinuation or "no call this year". Shown with the projected opening and deadline and the
cycles it rests on — *"expected to open March 2027 (opened 3 March 2026 and 4 March 2025); deadline
usually mid-May"* — and it becomes a roadmap item with a reminder before the projected opening.

**"Will it really run next year?" — what `UPCOMING` relies on, and what it does not.** Nobody can
guarantee a funder's next budget, so the system never rests on reputation ("everyone knows this one
runs every year") and never on a model's belief. It rests on **recorded evidence of recurrence, from
three general sources — the same three for every scheme, every family, every country**:

1. **observed consecutive cycles on the organisation's own pages** — its news or call archive, found
   by the crawl carrying the previous years' tokens;
2. **the same page as the Wayback Machine archived it in earlier years** — any URL, read through the
   vendor like any page, once, and cached for good;
3. **the funder register's cadence** — for a registered funder, a curated row `cadence` (`annual`,
   opening month, typical deadline month) carrying a **source URL and a verified-for-cycle date**,
   recorded once by a human from the funder's own documentation. This is how "everyone knows" enters
   the system: as a sourced fact that expires — verified within the last cycle it counts as
   recurrence evidence; older, it is a hint that raises re-check priority and verifies nothing.

Two consecutive cycles from any of the three, or a page stating the scheme runs every year and naming
the month, earn `UPCOMING` — shown as *"ran in each of the N cycles observed"*. A long-running national
scheme whose page never says "every year" qualifies through its archive and its register row, exactly
like any other. A gap year breaks the chain and the scheme is `UNVERIFIED` until its next call
appears. **No scheme, funder, country or page is named in code**; names appear only as rows of the
truth set and of the known-answer tests, which are data. A dated statement of suspension or
discontinuation always wins over history (the ChEMoinformatics+ case). And because history is not a
promise, two protections stand between the projection and the student: the weekly check from a
month before the projected opening, and the 45-day degrade with a notification — the student learns
the moment the world diverges from the plan. The same states and ladder apply to a **programme's own
application window** (the programme half of the option card), computed from its admissions page's
dates by the same function.

Everything else: **`CLOSED_FOR_INTAKE`** (this intake's deadline has passed and no later window
can serve that intake — offered for the *next* intake instead when the scheme recurs and the
student's plan allows a later start); **`SUSPENDED`** (a dated or intake-scoped `NO` wins for that
intake); **`ENDED`** (one-off scheme past its date; register grant period over with a silent page;
page `removed`); **`UNVERIFIED`** (the evidence found meets neither bar). **Only `OPEN` and
`UPCOMING` are shown as options.** `SUSPENDED` appears only as a note on a programme card the
student already has, with the quote — *"scholarship not offered for the 2026–2028 intake;
applicants must show alternative funding"*. The pack's coverage line reads *"N awards found, M
verified for your intake"*, so a thin result never reads as "no funding" (2026-09-13 design, test 3).

**The trade this makes, stated:** a scheme seen for the first time, with no call history anywhere on
its site and no "every year" statement, stays `UNVERIFIED` until its call appears — one observed
cycle is what earns `UPCOMING`. A first-year scheme has no cadence to project, and projecting one
would be the guess this section exists to forbid.

#### 3.5.2 The evidence ladder — each step only when the previous one found nothing decisive

| step | what | cost per organisation |
|---|---|---|
| **0. Own pages** | the pages already read for the award; the judge's new fields (3.5.3) supply intake, date and deadline | none beyond the read already paid |
| **1. Site crawl** | Firecrawl `/crawl` of the registrable domain on a **cycle vocabulary** of paths — call, apply, application, deadline, news, announcement and their local forms (`bewerbung`, `frist`, `ausschreibung`; `başvuru`, `son tarih`, `duyuru`; `müraciət`, `elan`; …) plus the current and next year tokens — `maxDiscoveryDepth: 2`, `limit: 15`, `allowSubdomains`, `changeTracking` on. A page reaches the reader only if its markdown mentions the award's name (or the scheme's short name) or a year token — string matching, no model. Typically 2–3 survive | ~$0.013 crawl + reader on the survivors |
| **1b. Recurrence** | the crawl vocabulary carries the previous two years' tokens as well, so a call archive on the site is found by step 1; when the site shows no history, the call page's **Wayback Machine** captures from the previous two cycles (`web.archive.org/web/<year>*/<url>`, fetched through the vendor like any page) are read once and cached for good — past cycles do not change | ~$0.002 fetch + reader once per scheme (~$0.10 today, ~$0.02 with the cheap first read) |
| **1c. Register cadence** | the funder register row's `cadence`, `cadence_source`, `cadence_verified_for_cycle`; recurrence evidence while verified within the last cycle, a hint afterwards | none |
| **2. One hop** | from the crawl's `links`, the one outbound link matching the apply/portal vocabulary (an admissions portal, an agency's application system), fetched as a single page, never crawled | ~$0.001 + reader on one page |
| **3. Search fallback (C)** | one Exa call with `includeDomains: [<registrable domain>]`, query `"<award name> <year> call for applications deadline"` in the local language, `numResults: 10`; hits read through the same filter. Brave `site:` as the second index only if Exa returns nothing | ~$0.007–0.03 + reader |

The ladder stops at the first step whose evidence meets the bar or settles it as `SUSPENDED` /
`EXPIRED` / `ENDED`. Off-site evidence is never used (owner decision: own site plus one hop).

#### 3.5.3 What the reader records — three fields, no extra model call

`LineVerdict` gains `applies_to` (the intake or period the line names, as written — `"2026-2028"`,
`"2026/27"`, `"Fall 2026"` — or `UNSTATED`), `stated_on` (an ISO date the line carries, or
`UNSTATED`) and `deadline` (an ISO date the line states as an application deadline, or `UNSTATED`;
pulled forward from increment 6 because verification cannot work without it). All three sit inside
the quoted line, so quote verification covers them. **Negations join their award**: a `negation`
line groups with the award of the same `(kind, scope)`; in a mixed group the more specific `NO` —
naming an intake or carrying a date — wins for that intake; a `YES` for another intake is its own
decision; equal specificity → `disputed: ("offered",)`. Evidence from steps 1–3 is joined to the
award by the judge's `name` and `kind`, each quote keeping its `source` and `stated_on`; the latest
date wins a contradiction. Intakes are normalised to a start year for comparison (`2026-2028`,
`2026/27`, `2026-27`, `2026` → 2026) by one tested helper.

#### 3.5.4 Re-verification, expiry, withdrawal

- Every evidence page carries Firecrawl `changeTracking`; a re-check on an unchanged page costs one
  credit and no reading.
- **Cadence:** monthly by default; **weekly** in the organisation's announcement season (the two
  months before last cycle's call date, when known); **daily** within 14 days of a known deadline.
- An `OPEN` award **closes itself** at its deadline → `CLOSED_FOR_INTAKE` for that intake and, when it
  recurs, `UPCOMING` for the next one — the projection is re-derived from the cycle just observed.
- An `UPCOMING` award is re-verified **weekly from one month before the projected opening**; when the
  call appears it becomes `OPEN`; if none has appeared **45 days past the projected date** it degrades
  to `UNVERIFIED`, the pack version bumps and the student is told (D.6's notification path).
- **Withdrawal:** when a page is re-read and an award whose *only* supporting source is that page is
  not among the read's decisions, the row is marked `WITHDRAWN`, `served: False`, quotes kept. The
  rule that a vaguer read of *another* page may not unserve a clearly stated award stands.
- **The register may not assert funding past the grant:** `I5` attaches to an EMJM from the EACEA
  record only for intakes inside the project's funded period (the record's dates — EMJM spec §2.2;
  confirm the field); after it, only the page decides.

#### 3.5.5 Data

`FundingCycleVerification` — one row per `(opportunity, intake_start_year)`: `state` (the six
values above), `evidence` (quotes with `source`, `stated_on`, `deadline`), `projected_open`,
`projected_deadline`, `cycles_observed` (the dated past calls the projection rests on),
`verified_at`, `next_check_at`, `ladder_step` (0–3), and **`cost_usd`** — Firecrawl credits × the plan's rate,
model tokens at list price, Exa `costDollars` — so the cost of every scholarship's verification is
recorded, not estimated. `FundingOpportunity` gains `suspended_for`, `suspension_quote` and
`WITHDRAWN` among its agreement values; the funder register (`Organisation`, or `SEED_FUNDERS` until it
exists) gains `cadence`, `cadence_open_month`, `cadence_deadline_month`, `cadence_source`,
`cadence_verified_for_cycle` — curated, sourced, expiring; the card reads the latest verification for the student's
intake. `cycle_validity(evidence, *, target_intake, today)` in `apps/funding/validity.py` is a pure
function — plain conditionals in the order `SUSPENDED`, `ENDED`, `OPEN`, `CLOSED_FOR_INTAKE`, `UPCOMING`, else
`UNVERIFIED` — never a model. The projection is arithmetic on the observed cycles' dates, never a
model's guess.

#### 3.5.6 Cost per scholarship, per cycle

| item | now | after the cheap first read (4.4), if it passes |
|---|---|---|
| step 0 only (well-kept page, dated call on it) | reader already paid → **~$0** | ~$0 |
| steps 1–2 (crawl + hop + reader on 2–3 pages, three readings) | **$0.10–0.35**, about half with prompt caching | **~$0.03** |
| recurrence evidence (step 1b), **once per scheme, cached for good** | ~$0.10 | ~$0.02 |
| step 3 (search fallback) | +$0.01–0.03 | same |
| monitoring between verifications (weekly change checks on 2–3 pages) | ~$0.01 a month | same |

So **$0.15–0.40 per scholarship per cycle** where the ladder runs, falling to about **$0.05**, and
near zero for pages that state their own call. A 2,000-organisation corridor: $300–800 per cycle
today, ~$100 later, paid once into the shared catalog. The sweep report prints **cost per verified
scholarship** and per corridor from the recorded `cost_usd`, replacing this table with a measured one
after the first run.

#### 3.5.7 Proof before any student sees a validity

- **Truth set:** ~40 organisations across the launch countries (AZ, TR, DE, NL, SE, FR, HU, IT),
  each labelled by hand from its own site — *open for the coming intake / suspended / expired / not
  stated* — with the sentence and page that prove it. Plus **historical cases from the Wayback
  Machine**: last cycle's version of the same pages, so `EXPIRED` and `SUSPENDED` transitions carry a
  known outcome (the current page).
- **Known-answer set, one real page per state**, pinned in the reader's tests: `SUSPENDED`
  (ChEMoinformatics+, 2026–2028), `OPEN`, **`UPCOMING`** (a March–May scheme evaluated in
  September, two past calls on its site — the owner's case), `CLOSED_FOR_INTAKE`, `ENDED`,
  `UNVERIFIED` (a first-year scheme with no history). Named pages are rows here, never logic.
- **Gate:** precision on `OPEN` and on `UPCOMING` each ≥ 95% (a wrong "verified" is the worst
  card); for `UPCOMING` a second number — of last cycle's projections, the share whose call opened
  within 45 days of the projected date, measured from the Wayback rows; recall reported honestly per
  ladder step; **zero** `OPEN`/`UPCOMING` awards whose own pages contradict them; cost per
  verified scholarship reported. D.3's 30-card precision check counts a card shown as open for an
  intake its evidence excludes as a false card. The 58-host re-run (Task 7) reports how many award
  groups carried a negation.

#### 3.5.8 Whose deadline? — a deadline is a rule, not a date (owner's point, 2026-09-18)

Deadlines differ by who the applicant is and how they apply: DAAD sets a different date per
country of origin (applications go through the local DAAD office or embassy); universities give
non-EU applicants an earlier date than EU ones, and scholarship applicants an earlier one than
self-funded; nomination schemes — any award a university nominates for — have an **internal**
deadline set by the nominating university weeks before the funder's official one; some calls run in
rounds. A single `deadline` field would pick one of these at random and be wrong for most students.

- **The reader records the condition with the date.** Every deadline line carries `deadline_for` —
  the condition *as written* (`"applicants from India"`, `"non-EU citizens"`, `"self-funded
  students"`, `"nominating institutions"`, `"round 2"`) or `ALL`. It is part of the quoted line, so
  quote verification covers it; no extra model call.
- **A small mapper normalises it** to a closed vocabulary — `ALL`, `NATIONALITY:<ISO2 or region>`,
  `RESIDENCE:<ISO2 or region>`, `APPLICANT_CLASS: EU | NON_EU | DOMESTIC | INTERNATIONAL`,
  `FUNDING: SCHOLARSHIP | SELF_FUNDED`, `ROUTE: NOMINATION | DIRECT`, `ROUND:<n>` — country and
  region names resolved through Wikidata labels and aliases per language (data, never a hand-typed
  table — the resolver's lesson), anything unmapped kept verbatim as `OTHER:<text>` and shown, never
  dropped.
- **The pack selects the student's deadline**: the most specific condition the student's profile
  satisfies (nationality, residence, EU/non-EU derived from nationality against the destination,
  funding need, route), falling back to `ALL`. When a condition exists for the student's group but
  its date was not read, the card says so in the P1-9 style — *"deadline differs for applicants from
  <country>; not read on the page"* — rather than showing the general date as if it applied.
- **Nomination routes look on the institution's side.** For an award whose route is
  `INSTITUTION_NOMINATES` and which is attached to a programme in the pack, the ladder also runs over
  the *institution's* pages for the award's name (step 0–1 on that domain) to find the internal
  deadline. Found → shown as *"university's internal deadline 15 Nov 2026; official submission 8 Jan
  2027"*. Not found → *"the university sets an earlier internal deadline — not stated on its pages;
  official deadline 8 Jan 2027"*. Never an invented margin.
- **Verification uses the student's deadline.** `cycle_validity` selects the applicable deadline
  before deciding `OPEN` / `CLOSED_FOR_INTAKE`: a scheme whose Indian-applicant deadline has passed is
  `CLOSED_FOR_INTAKE` for an Indian student while still `OPEN` for another; the projection for
  `UPCOMING` is made from the student's condition's past dates when they exist, else from `ALL`.
- **Data:** `evidence.deadlines` is a list of `(date, condition, quote, source)`; the card stores the
  selected one and the condition it matched. The truth set (3.5.7) includes at least ten
  conditional-deadline rows (a DAAD per-country page, an EU/non-EU university page, a nomination
  scheme with an internal date on a university page).

#### 3.5.9 Generality — the owner's standing instruction

Every rule in §3.5 applies to **every funding family, every holder, every country and script, and to
a programme's own application window**. Nothing in code names a scheme, a funder, a country or a page;
the per-language vocabulary comes from data (Wikidata labels, the register), not from hand-typed
constants; and the concrete cases in this section — a joint master whose intake lost its
scholarship, a March–May window seen in September, a national scheme with per-country deadlines, a
nomination scheme with an internal date — are the truth-set rows the general rules must pass, never
special cases the rules were written for.

## 4. B — one vendor fetch path, used to the hilt (owner decision 2026-09-18, evening; third tier added 2026-09-19)

Supersedes the four-tier ladder this section held earlier the same day. The owner's instruction:
*"make sure we are using Firecrawl on maximum its capabilities."* The 2026-09-15 decision — we
cannot out-build a scraping vendor — stands and is now carried through instead of hedged: the
Scrapling tier, the browser task and the research egress proxy are **retired for the research
path** (deletion plan, increment 3), not kept as a fourth fallback. Every capability below was read
from Firecrawl's own API reference on 2026-09-18.

### 4.0 Tier zero — an honest client, before any vendor is paid

Measured 2026-09-19 on `globed.eu/how-to-apply/`, one of the hosts the 2026-09-18 recovery run
recorded as `SourceBlocked: source returned HTTP 403`:

| request | result |
|---|---|
| no `User-Agent` (what `egress.py` sent) | **403** |
| `python-urllib3/2.0` | **403** |
| `TehsilAgent/1.0 (+https://…)` | **200** |
| browser mimic | 200 |
| curl, any header set | 200 |

Not headers in general and not TLS: connecting to the resolved IP with SNI pinned, our SSRF shape,
made no difference — `403` by hostname too. The site refuses a client that does not say who it is,
which is an ordinary posture and not a bot wall.

So `egress.py` now sends `USER_AGENT`, a stable identifier with a contact URL, defaulted per request
and overridable by a caller that has its own (`europass.py` speaks to an API). CLAUDE.md's egress
rule chooses the form: identifiable, never a browser string — a browser mimic also returned 200 and
is still not what goes there.

**It did not shrink the vendor tiers, and that was measured rather than assumed.** The hypothesis
was that the 2026-09-18 residue had been measured with a headerless client and would shrink once the
client identified itself. Run against the same 58 hosts on 2026-09-19 it did **not**: tier zero
refuses **9 of 58**, against the 8 recorded the day before. The User-Agent fix is real — it recovered
R-056 (GLOBED, `europass_required`), one of the fifteen labelled rules the recovery run lost — but it
recovered it in the *CV-corpus* population, not this one. Two populations, two different answers; do
not carry a result between them.

### 4.0a The ladder, measured end to end on the 58 hosts (2026-09-19)

| tier | outcome | what it recovered |
|---|---|---|
| 0 — our client | **49 / 58** | — |
| 1 — Firecrawl (`proxy: "auto"`) | **+5 of the 9** (6 in principle — see the correction below) | two 403s (`fintables.com`, `bm.ge`); two broken TLS chains (`mes.gov.ge` UNEXPECTED_EOF, `hwg-lu.de` CERTIFICATE_VERIFY_FAILED); one connect timeout (`bildungsserver.de`) |
| 2 — scrape.do | **+1 of the 3** | `mischolarship.com`, and only at `render=true&super=true` — **25 credits**, 889 bytes |
| unreachable | **2** | `bekaiafund.org`, `worldscholarshipforum.com` — 502 from the origin to every tier, i.e. dead, not blocked |

**Correction to this table: `freiheit.org` was never a Firecrawl recovery through our own path,
and counting it as one was the mistake, not the https rule.** The earlier version of this table
listed `freiheit.org` (http-only) among Firecrawl's six recoveries. `discovery.canonicalize_url`
raises `"official sources must use HTTPS"` before any URL reaches a vendor at all, so a host that
answers only on http never gets far enough to be handed to Firecrawl in the first place — the
recovery was measured by calling the vendor directly, outside `egress.py`, which is not the door a
real fetch uses. Firecrawl recovers 6 of the 9 refused hosts **in principle**; **5 of 9 through the
fetch path this system actually calls** (`fintables.com`, `bm.ge`, `mes.gov.ge`, `hwg-lu.de`,
`bildungsserver.de` — the table above). The https-only rule stands — it is a deliberate provenance
rule, not an accident this measurement should be read as arguing against: `canonicalize_url` is
what gives an `OfficialSource` its identity, and it still raises before any vendor sees the URL.

**So the antibot case that actually needs a residential proxy is 1 host in 58.** Firecrawl's six are
mostly not bot walls at all: they are TLS, scheme and timeout failures that a vendor absorbs because
`skipTlsVerification` and its own retry budget are its job. scrape.do charges **0 for a failed
fetch** (measured on both 502s), so a miss at tier 2 costs nothing but latency.

**The two vendors are not the same kind of thing, and the routing follows from that.** Firecrawl is
an **extractor**: it returned the Rhodes CV template as 2,667 characters of text, and SI's `.docx` as
readable content. scrape.do is a **transport**: the same PDF came back as `%PDF-1.6`,
`content-type: application/pdf`, 77,522 raw bytes — correct, and useless to a reader without a parser.

**Stated precisely, because the short version is wrong.** scrape.do *does* have an `output=markdown`
(measured 2026-09-19: globed at 7,841 characters for 1 credit), so it is not HTML-only. What it does
not have is *content* extraction — that markdown opens `- Meta: charset: utf-8`, `- Meta: name:
viewport`, i.e. it converts `<head>` too, against Firecrawl's `onlyMainContent`. And `output=markdown`
on a PDF is **silently ignored**: the same 331KB of `%PDF-1.6` comes back. Confirmed against their
documentation the same day: no PDF or office parsing, no crawl, no site map, no change tracking. It
does have sessions, `geoCode`, `waitSelector`, `blockResources`, `playWithBrowser`, screenshots, an
async API, and `transparentResponse` — the last being the deliberate way to ask for unprocessed bytes.

That cuts the other way for provenance: §4.3 already records that Firecrawl's `rawHtml` is its own
rendering rather than origin bytes (FAU 189,682 vs 422,515), and scrape.do hands back what the origin
actually sent. **Firecrawl for reading, scrape.do when the bytes themselves have to be defensible.**

**A cost hazard that has no request-time signal.** scrape.do applies **per-domain multipliers of 10 to
200 credits** server-side (`google.*` 10 with forced residential; `sainsburys.co.uk` 200). Nothing in
the request says so, and the tariff in §4.1b does not predict it. `Scrape.do-Request-Cost` on the
response is the only authority — record it per host, and hold a per-sweep credit budget rather than a
per-call price. This is the one line item on the whole fetch path that can surprise anyone.

### 4.1 The path — which capability does which job

| job | Firecrawl capability | how it is used here |
|---|---|---|
| **Fetch a page** | `POST /v2/scrape`, `formats: ["markdown", "html", "changeTracking"]`, `proxy: "auto"` (basic → enhanced escalation at +0 credits), `onlyMainContent: False`, `parsers: [{type: "pdf"}]`, `skipTlsVerification` (**default true** — reads Georgia's education ministry, whose broken chain refused our egress), `blockAds`, `removeBase64Images`, `location: {country: <organisation's country>, languages: [<local>]}`, `timeout` up to 300 s | 1 credit per page. **Every scrape is a fresh fetch**: a request carrying `changeTracking` bypasses Firecrawl's index cache and ignores `maxAge` (their docs, 2026-09-18), so the two-day default cache never applies on this path — and that is the right trade: one fresh credit (≈ $0.001) against a ~$0.35 reader run avoided on an unchanged page. The 60-day deadline rule decides *when* a page is re-scraped, never whether the copy is fresh. HTML, not markdown, lands in `body` (`text/html`), because every downstream consumer parses markup off it — `harvest.anchors`, `search._sitemap`, `reader.readable_text`, `harvest.content_digest` — and a markdown body made every `HtmlCatalogue` yield zero leads and left `content_sha256` empty, defeating the unchanged-page cache. `onlyMainContent` is **False**, not the default true: anchor harvesting needs exactly the navigation links that option strips, which is safe only because `reader.readable_text` narrows to the admission sections itself on the way to the model |
| **Did the page change?** | `changeTracking` in git-diff mode — **free**; `changeStatus` ∈ `new / same / changed / removed`, compared against our team's last scrape of the same URL and `tag` | `same` → the reader is not run; `changed` → the diff names the lines; `removed` → reachability. Scrape options must be identical per URL (their documented caveat), one `tag` per cadence. Our `harvest.content_digest` stays as the second opinion until a sweep shows the two agree |
| **Site traversal** | `POST /v2/crawl`: `includePaths` (funding-word regexes per language, from `FUNDING_PATH_TERMS`), `limit` (≤ 25 pages per host per sweep), `maxDiscoveryDepth: 2`, `allowSubdomains: true`, `sitemap: "include"`, `ignoreQueryParameters: true`, `scrapeOptions` as above | replaces the homepage-plus-three-links walker (`funding_links`). Polled as a job; webhooks when the web tier has a signed endpoint |
| **Inventory** | `POST /v2/map`: `includeSubdomains` (default true), `limit` up to 100,000, `search` as a *ranking* for funding words | unfiltered `/map` is the fallback — the filter can return zero for a site that unfiltered returns 76 for (measured 2026-09-15) |
| **Hub harvesting** | `POST /v2/extract` with a closed schema over `https://<hub>/*`, `showSources: true`, `enableWebSearch: false` | ministry and agency pages → `{organisations: [{name, kind, url?}]}`; never discovery |
| **The cheap first read** | `formats: [{type: "json", schema, prompt}]`, +4 credits per page | one vendor-model read returning **our** closed schema with a quote per verdict; quotes verified mechanically against the same call's markdown — §4.4 measures it before it decides anything |
| **Content behind interaction** | `actions` (click, scroll, wait, write, executeJavascript; "Interact", 2 credits per browser-minute) | only when a scrape returns a shell — a recorded reason per host, never a default. Every interaction is followed by `{"type": "wait", "milliseconds": 2000}` so a client-rendered table has loaded before capture; interaction runs also bypass the cache, which changes nothing here |
| **Bulk** | batch scrape and crawl jobs, `maxConcurrency`, `delay` | corridor sweeps run as jobs and are polled; a Standard plan gives 25 concurrent browsers and 500 requests/min |
| **Off, with the reason** | `/search` for discovery (unnamed upstream index — its terms cannot be read; measured weakest first-discoverer, 22 of 353) except the PDF category channel; **Agent** (autonomous browsing paying model tokens per step — the dearest way to read a page); `profile` (no logins — portals are out of this system); `zeroDataRetention` (no PII travels this path) | |

**Second vendor, own egress.** Tavily Extract was the fallback when Firecrawl fails or is down —
measured identical content on 2026-09-15 and its terms are cleared. **scrape.do takes that job as of
2026-09-19** (§4.1a): it covers the same outage case and is the only tier that also covers a host
that blocks, so keeping a third fetcher for the easy half of one failure mode is a tier nobody reads.
**Tavily keeps its other roles unchanged** — `/map` for host inventory and name-to-site resolution
(roster §4.13) — and neither is something a fetcher can do, so this narrows Tavily's job rather than
retiring it. Our own egress fetches **only `europa.eu`** (student PII; pinned address;
DNS-rebinding guard) — no vendor ever touches it, and a test asserts so.

### 4.1a Third tier — scrape.do, on the residue only (owner decision 2026-09-19)

Adopted for the hosts that beat `proxy: "auto"` and the Tavily fallback. It lifts the
"no paid solving service is ever added" line recorded in CLAUDE.md on 2026-09-13; that line
protected our *shared egress address* from being burned on challenge-solving, and a vendor
solving from its own address spends nothing we own. **The portal exclusion is untouched and is
not a cost rule:** `apps/portals/` still detects a CAPTCHA and hands it to a human, because
there the agent acts as an authenticated applicant and `phased requirements.md` §2 / §3.4 forbid
circumventing a portal's access controls. No fetch vendor is ever pointed at a portal.

**Read from their own documentation, 2026-09-19 — not inferred:** a GET API taking `token` and
`url`, with `render` (browser rendering), `super` (residential proxy), `geoCode` (2-letter
country), `regionalGeoCode` and `customHeaders`; a proxy mode and an async job API also exist and
are not used here. Cost is **1 credit** for a datacenter request and **25** for residential plus
JS rendering, and the `Scrape.do-Request-Cost` **response header is authoritative** — domain-specific
server-side configuration can change the price of a call, so the header is what gets recorded, never
a tariff copied into our code.

That 25x is the whole reason this is a residue tier and not a default. The escalation is
`render`/`super` **off first**, and each is turned on only for a host recorded as needing it —
the same per-source shape `solve_cloudflare` had, for the same reason: a blanket setting turns an
unknown number of 1-credit reads into 25-credit ones with nothing to show which needed it.

`fetched_via = SCRAPE_DO` joins the labels in §4.3, and the final URL runs through
`validate_public_url` exactly as the other two vendors' do. **Unverified until a key exists:**
every cost figure above is a published tariff, not a measurement, and the §4.5 gate is where the
residue's real size and price get recorded.

### 4.1b The economics — measured 2026-09-19, and they say not to optimise the fetch

Credits are not comparable between vendors; dollars are. Firecrawl Standard is $83 / 100k credits
($0.00083 each); scrape.do Hobby is $29 / 250k ($0.000116 each) — **scrape.do is 7x cheaper per
credit**, so its dear tiers are not dear in money.

| tier | $/page | x a Firecrawl scrape | % of one reader run |
|---|---|---|---|
| scrape.do datacenter | 0.000116 | 0.1x | 0.03% |
| scrape.do dc + browser | 0.000580 | 0.7x | 0.17% |
| **Firecrawl scrape** (markdown + free `changeTracking`) | 0.000830 | 1.0x | 0.24% |
| scrape.do residential | 0.001160 | 1.4x | 0.33% |
| scrape.do residential + browser | 0.002900 | 3.5x | **0.83%** |
| Firecrawl JSON read (+4) | 0.004150 | 5.0x | 1.19% |
| scrape.do 200-credit domain | 0.023200 | 28.0x | 6.63% |
| **the reader** (3 statement reads + 3 judgements) | **0.350000** | **422x** | 100% |

**The whole 58-host sweep costs 4.8 cents to fetch. One avoided reader run saves eight times that.**
A Firecrawl scrape is 0.24% of reading the page it fetched; scrape.do's *dearest* ordinary tier is
0.83%. So "expensive scrape.do" is a credit-denominated illusion: 25 credits is $0.0029.

**What follows, and it is mostly "stop thinking about this":**

1. **Firecrawl stays the default despite being 7x dearer per credit.** `changeTracking` is free and
   skips a $0.35 reader run on an unchanged page — that one feature pays for 420 fetches. Extraction
   is included, and a bad extraction costs a full reader run spent on garbage, which dwarfs the credit
   gap. Measured 2026-09-19: **a Firecrawl hard failure charges nothing** (710 credits before and
   after a DNS failure), so trying it first is free when it loses. Their docs add the asymmetry: a
   403/404 *does* cost 1 credit.
2. **On a Firecrawl failure, go straight to `render=true&super=true` — do not build a ladder.** A host
   that beat `proxy: "auto"` has already beaten one vendor's own escalation; measured, scrape.do's
   cheap tiers recovered **0 of the 3** such hosts, and its soft failures charge (mischolarship.com
   returned HTTP 200 with 469 bytes of nothing, billed 1 credit). Being wrong costs $0.0029 — less
   than the engineering time to decide. The ladder is a rung nobody should write.
3. **The one fetch cost worth engineering against is the per-domain multiplier** — up to 200 credits,
   applied server-side, with no request-time signal. Record `Scrape.do-Request-Cost` per host and hold
   a per-sweep credit budget; that is the only place a fetch bill can surprise anyone.
4. **The optimisation that is actually worth running is §4.4** — the 5-credit JSON read against the
   $0.35 judge, an 84x cut on the term that dominates everything above. After that, `_READS = 3`
   itself: one read fewer saves $0.12 a page, which is 145x the entire fetch saving of a whole sweep.

> **Withdrawn 2026-09-22 — see §4.1d, item 1.** The paragraph below asks for scrape.do fetches and
> Firecrawl `changeTracking` on the same pages, and change tracking only compares against Firecrawl's
> own previous scrape. Kept as the record.

**Under the free tiers this reverses, and that is the near-term position.** Both accounts are on
1,000 credits/month (Firecrawl showed 710 remaining on 2026-09-19). The binding constraint today is
*quota*, not dollars, and scrape.do's 1,000 buy far more pages than Firecrawl's because nothing else
competes for them. So until a plan is bought: **fetch ordinary pages with scrape.do and spend
Firecrawl's credits only on what only Firecrawl does** — crawl, map, `changeTracking`, PDF and office
parsing, the JSON read. Local extraction covers the rest (`reader.py::readable_text` for HTML, `pypdf`
for PDFs, both already in the tree). Flip back to rule 1 the day a Firecrawl plan is bought.

### 4.1c Free tier or paid — measured 2026-09-19, and the answer is "free until the first corridor"

**Neither free tier gates a capability. Both gate rate and volume.** Firecrawl's free plan carries
every endpoint — scrape, crawl, map, search, extract — at 10 scrape/min, 2 crawl/min and 2 concurrent
browsers. That is documented, and more to the point it is *measured*: on the free key, `proxy: "auto"`
recovered six of our nine refused hosts, and `parsers: [{type: "pdf"}]` turned the Rhodes CV template
into text. scrape.do publishes no free-tier limits at all, so the only reliable statement is the
measured one: **`render=true&super=true` — its dearest 25-credit path — succeeded on the free key.**

So nothing is bought to unlock a feature. A plan is bought to buy *volume*, and the threshold is
legible:

| | pages/month | free tier (1,000) |
|---|---|---|
| today — a 58-host sweep | 58 | 6% |
| today — the 20-programme CV corpus | ~60 | 6% |
| **one pass of a 2,000-organisation corridor** (§3.5.6, 2–3 pages each) | **5,000** | **5x over** |
| its residue to scrape.do (3 of 58 measured, failures free, 25 credits on the third that works) | 259 → **2,155 credits** | 2.2x over |

**So: stay free now, and buy on the day the first real corridor sweep runs — not before.** Current
work is measurement-scale and sits inside 6% of either quota. Announcement-season weekly and
deadline-daily re-checks push the corridor figure higher again, so 5,000 is the floor, not an estimate.

**What to buy, when that day comes.** Firecrawl Standard ($83 / 100k) — a corridor pass spends 5% of
it, which is the headroom the weekly and daily cadences eat. **Firecrawl Hobby ($16 / 5,000) is a
trap**: one pass consumes the entire month. scrape.do Hobby ($29 / 250k) uses **0.9%** of its quota on
the residue, so it is bought for the quota floor rather than the volume — and if the residue stays at
the measured 5%, scrape.do may never need a plan at all beyond that first step.

**One caveat against reading §4.1b too hard.** There the fetch was 0.24% of reading a page. At
corridor scale the ratio is not that kind: $112 of plans against §3.5.6's $300–800 of reader spend per
cycle is **15–25%**, because `changeTracking` stops the reader running on most pages while every page
is still fetched. Fetch is the minor term, not a rounding error, and it becomes the *dominant* term on
a corridor whose pages mostly do not change.

### 4.1d Re-read against both vendors' own documentation, 2026-09-22

> **Superseded in part, 2026-09-22 (later the same day):** with both plans paid, the fetch path is
> now designed in `2026-09-22-fetch-engine-design.md`; item 1 below is amended by its §3 (`purpose`
> replaces the one-shot rule). The rest of this section stands as the documentation record.

The owner asked whether both vendors are used to the full and whether the path is cost-optimised.
Every statement below was read from `docs.firecrawl.dev` (billing, rate-limits, the scrape reference,
crawl, map, parse, document-parsing, change-tracking, enhanced-mode, fast-scraping, monitoring,
webhooks) and `scrape.do/documentation` (parameters, request-costs, pricing) on 2026-09-22. Where this
section contradicts §4.1–§4.1c, this section wins; the older text stays as the record.

**Confirmed, unchanged.** Enhanced proxy is 1 credit and an escalation is not charged — it fires only
on 401/403/429, at most once per request. `changeTracking` in git-diff mode is free, requires
`markdown` in the same request, bypasses the index cache and ignores `maxAge`, is matched on exact
source URL + team + `tag`, and its snapshots never expire. A document returned with a 403/404 costs
1 credit; a scrape that returns no document costs 0. JSON, question and highlights formats add 4
credits per page. Firecrawl parses `.docx/.doc/.odt/.rtf/.xlsx/.pptx/.epub/.csv` from a URL through
`/scrape`. scrape.do: 1 / 5 / 10 / 25 credits for datacenter / +browser / residential / both; failed
requests are free (2xx, 400, 404, 410 count as success); `Scrape.do-Request-Cost` is authoritative and
a second header, `Scrape.do-Remaining-Credits`, exists. Free plans: 1,000 credits each; Firecrawl 2
concurrent browsers, 10/min scrape and map, 2/min crawl; scrape.do 5 concurrent, every feature. `/map`
is **1 credit per call** whatever `limit` returns.

**Corrected — four things §4.1–§4.1b had wrong.**

1. **The free-tier reversal in §4.1b is withdrawn; cadence decides the vendor.** It told us to fetch
   ordinary pages with scrape.do and "spend Firecrawl's credits only on what only Firecrawl does —
   `changeTracking`". Those cannot both hold for one page: change tracking compares against
   *Firecrawl's own* previous scrape of that URL, so a page fetched through scrape.do has no baseline
   and the next Firecrawl read of it is `new`, never `same`. The rule is now: **a page the reader will
   read, or that will be re-checked on any cadence, goes through Firecrawl from its first fetch** —
   the extraction is what the reader needs and the baseline is what the monthly check needs.
   **scrape.do takes the one-shot, bytes-only fetches** — organisation-name harvesting from an
   aggregator, homepage liveness, the by-hand reads that build the labelled corpus, and anything where
   the origin's own bytes must be defensible (§4.0a) — plus the residue after Firecrawl fails, as
   §4.1a already says. The routing is the same whether the accounts are free or paid; a plan changes
   quota pressure, not the rule.
2. **PDF is billed per PDF page, not per document.** §4.1 lists `parsers: [{type: "pdf"}]` beside the
   1-credit scrape as if it were free. A 40-page guideline is 40 credits; a 200-page handbook 200. It
   is the one Firecrawl cost that is *predictable*, unlike scrape.do's multipliers: set
   `parsers: [{type: "pdf", maxPages: 60, pageMarkers: true}]`, compare `metadata.totalPages` with
   `metadata.numPages`, and record a truncated read as `PARTIAL` carrying both numbers — a rule on
   page 61 is a bounded miss, never a silent one. `parsers: []` returns the raw PDF as base64 for
   1 credit flat, which is how a snapshot digest is taken without paying per page. `pages`, `blocks`
   and `pageMarkers` cost nothing, and `pageMarkers` is on: a quote then carries its page number,
   which the corpus's location label needs.
3. **`location` is left unset.** §4.1 sets `location: {country: <organisation's country>}` on every
   scrape. Firecrawl's own guidance: "We highly recommend leaving `location` unspecified unless you
   are sure you need it" — an unsupported country silently falls back to EU/US, and `location` is
   part of cache and change-tracking consistency. It is set per host only where a page is measured
   geo-gated, recorded exactly as `render`/`super` are for scrape.do.
4. **`proxy` is deprecated; `auto` is the default.** The request no longer passes it.

**Added — capabilities the spec did not know exist, each with what it replaces.**

5. **Monitoring (`/v2/monitor`) is the monthly change check, and it is on the free plan.** A monitor
   takes 1–50 targets (`scrape` for a known URL, `crawl` for a whole site), a schedule as cron
   (`0 6 1 * *` for monthly) or plain text for daily and weekly, keeps snapshots for `retentionDays`
   (30 by default, up to 365), and reports every page as `same / new / changed / removed / error` —
   by webhook per page (`monitor.page`) and per check (`monitor.check.completed`), or by polling
   `GET /v2/monitor/{id}/checks`. **No per-monitor fee: each check pays 1 credit per page it
   scrapes**, and the create call returns `estimatedCreditsPerMonth`. This replaces the
   EventBridge-cron-plus-`changeTracking` loop the storage design was going to build, and the
   "60-day deadline rule decides when a page is re-scraped" in §4.1: the cadence is a monitor
   property, one monitor per admissions cycle, and our code owns only which URLs are on it and what
   happens on `changed`. An optional plain-language `goal` ("changes to CV, résumé or
   application-document requirements") adds a judge at **1 credit per changed page only**; a
   `changed` page judged not meaningful does not wake the $0.35 reader. The judgment is a vendor
   model's opinion and is used as a *trigger*, never as a rule — the reader still verifies every
   quote against the page. A `crawl` target also answers a question the design had no answer for: a
   **new** requirements page appearing on a site is not a change to any known URL, and website
   monitoring reports it as `new`.
6. **`GET /v2/crawl/{id}/errors` is where "blocked" and "unreachable" live.** The status counters
   cannot say anything failed — `completed == total` on every finished crawl, failed pages excluded
   from both. That endpoint returns `errors[]` (network, timeout) and `robotsBlocked[]`. The
   four-outcome crawler reads it; a crawl that "completed" without it has been read as "found
   nothing", the failure mode this repo has met twice. A page the site answered with 404 is in `data`,
   not in errors, with `metadata.statusCode`.
7. **`/v2/parse` takes uploaded bytes (50 MB), so ZIP needs no parser of ours.** `zipfile` from the
   standard library opens the archive; each `.pdf`/`.docx` member goes to `/parse` and comes back as
   markdown under the same options as `/scrape`. The "DOCX and ZIP" fetching item shrinks to that.
8. **Firecrawl's crawl respects `robots.txt` and cannot be told not to** (`ignoreRobotsTxt` is
   Enterprise-only); blocked URLs are enumerated in `robotsBlocked`. On the crawl path the politeness
   question CLAUDE.md assigns to the vendor is therefore answered and not optional. `delay` forces
   concurrency to 1 for a host that asks for it.
9. **Crawl results are non-deterministic between runs** — Firecrawl says so: concurrent discovery,
   `data` ordered by finish time, branches near the depth boundary explored to different extents.
   Two consequences: corpus crawls set `maxConcurrency: 1` and keep `sitemap: "include"` (`skip`
   misses PDFs listed only in the sitemap); and the live discovery gate scores "found on any of N
   runs" with N recorded, never set equality — the lesson `tests/research/test_reader.py` already
   learned for the reader.
10. **A per-key spend limit is the hard stop; `FETCH_CREDIT_BUDGET` is the soft one.** Firecrawl caps
    an API key in credits per day, week or month from the dashboard, enforced by them. Our in-process
    budget survives only as long as our accounting is right; the key limit survives a bug in it. Both
    are set: the key limit at the corridor budget, ours below it, so a sweep stops on a
    `FetchBudgetExhausted` we can read rather than a 402 we cannot. scrape.do has no equivalent;
    `Scrape.do-Remaining-Credits` is read on every response and a sweep stops at a floor.
11. **Webhooks carry `X-Firecrawl-Signature`, HMAC-SHA256 of the raw body under the account's
    webhook secret** (Advanced tab of settings → `FIRECRAWL_WEBHOOK_SECRET`, never a settings
    default). Verify with `hmac.compare_digest`, answer 401 on mismatch, respond 2xx within 10 s;
    three retries at 1 / 5 / 15 minutes, then marked failed. Until a public HTTPS endpoint exists —
    nothing is deployed — the worker **polls** monitor checks and crawl jobs instead; polling costs
    no credits.
12. **Cached scrapes still cost 1 credit** ("caching improves speed and latency, not credit usage").
    Nothing about `maxAge` is a cost lever; it never was on this path, because `changeTracking`
    bypasses the cache. Recorded so nobody proposes it.

**Still off, each with the reason.** `highlights` / `question` / `summary` formats (+4 credits): a
vendor model choosing sentences is a fourth reading we cannot verify by code, at the same price as the
§4.4 JSON read that *is* schema-bound and quote-verified. Crawl `prompt` (natural language →
crawler options): non-deterministic generation of a configuration we can state exactly.
`onlyCleanContent` (LLM boilerplate removal, beta): `onlyMainContent` is deterministic and measured.
`/agent`, `/search`, `profile`, `redactPII`, `lockdown`: as §4.1 — nothing here changes them.
`/extract` is now billed at 15 tokens per credit and is being superseded by `/agent`; the hub-harvest
role in §4.1 keeps it only until the register work measures a plain crawl + JSON read against it.

**The per-domain table, read in full.** scrape.do's surcharged domains are e-commerce, SERP, social
and classifieds (`google.*` 10, `linkedin.com` 30, `shopee.*` 100, `sainsburys.co.uk` 200). **No
university, ministry, agency or foundation host is on it**, so the 200-credit surprise §4.1b engineers
against is real in principle and improbable in this population; the header check stays because the
list is theirs to change.

**What this does to the cost table in §4.1b.** Two lines are added and nothing is removed: PDF at
1 credit per page (a 30-page guideline is $0.025, 7% of one reader run); the monitor judge at 1 credit
per changed page (a page that changed and is judged noise costs $0.0008 instead of $0.35). The
conclusion — the reader is the term, the fetch is not — stands, and that second line moves more money
than anything else in this section.

### 4.2 The retry queue

A host that fails both vendors with a *network* class of error (TLS that even `skipTlsVerification`
cannot pass, connection timeout, HTTP 5xx) is **`UNREACHABLE`**, retried three times over seven days,
then queued to a person (C.3) only if it is a plausible funder. The bot-block class no longer exists
as a category — `proxy: "auto"` is the vendor's job, and what survives it goes to scrape.do (§4.1a)
before anything is called unreachable. `UNREACHABLE` now means all three tiers failed, which makes it
a much stronger claim than it was on 2026-09-18 and the reason the §4.5 gate is worth re-running.

### 4.3 What is kept

Snapshots store the vendor's **HTML**, labelled `fetched_via = FIRECRAWL | TAVILY_EXTRACT | SCRAPE_DO | EGRESS`.
(Amended 2026-09-19, whole-branch review: this said *markdown*, and it shipped that way. Four
consumers parse markup off the stored body — `harvest.anchors`, `search._sitemap`,
`reader.readable_text`, `harvest.content_digest` — so a markdown body silently emptied every
HTML catalogue and every change digest. Firecrawl is asked for both formats at the same one
credit; the markdown is requested because `changeTracking` requires it, not because anything
reads it. See CLAUDE.md, Web fetching.)
`metadata.url` (the final URL after redirects) runs through `validate_public_url` before it becomes
provenance — a private-address or credential-carrying final URL is rejected exactly as before.
~~**scrape.do's provenance is request-URL-based, not response-based, and that is a real difference
from Firecrawl.** A captured live response carries `scrape.do-initial-status-code` and
`scrape.do-detected-waf` but reports no final URL of its own, so `final_url` for that tier is the
URL we asked for.~~ **Wrong, and corrected 2026-09-19 against the live vendor.** That reading came
from a capture taken at the 1-credit tier. At `render=true&super=true` — the **only** tier this
system ever reaches scrape.do on — the response carries **`scrape.do-resolved-url`** and
`scrape.do-target-url`. So `final_url` for this tier is now the vendor's own report of where it
landed, read through the case-insensitive header lookup, `validate_public_url`d, and **absent is a
failure, never a fallback to the requested URL** — the same rule Firecrawl's `metadata.url` gets.
`reader.require_same_origin` therefore compares two real origins on both tiers.

The guard this replaces was measured refusing correct answers at 25 credits each: `disableRedirection`
plus "refuse any non-2xx `scrape.do-initial-status-code`" rejected `https://globed.eu/how-to-apply/`
as *"origin answered HTTP '301'"* — a Cloudflare bounce landing on the identical URL, on a page that
answers 200 to a direct request. The initial status is now read for the log only. **The limit,
stated exactly:** for HTTP redirects the resolved URL is the landed location; for a meta-refresh or a
JS navigation under `render=true` it is *plausibly* the browser's final location — undocumented and
unmeasured. Do not record that as closed.

Firecrawl's `data.metadata.url` is the vendor's own report of where it landed, re-validated as such.

**A PDF never reaches scrape.do.** Measured 2026-09-19: Firecrawl returns the Rhodes CV template
through its **`html`** format as the document's own parsed text in real markup
(`<html><body><h1>RHODES SCHOLARSHIPS – CURRICULUM VITAE (CV) – TEMPLATE</h1>…`), 2,842 bytes,
`metadata.contentType: application/pdf`, 1 credit — which `reader.readable_text` parses like any
page. The line above about scrape.do returning `%PDF-1.6` raw bytes is still true of scrape.do and
now irrelevant: the residue tier is never asked. `firecrawl.py`'s refusal of an empty `html` keeps no
markdown fallback, and that decision stands on its own — an empty `html` must stay a loud failure,
never a silent degrade to a body that yields zero anchors.

**XML sitemaps are NOT on the vendor path — they are data files, with CSVs and JSON.** Measured
2026-09-19: Firecrawl's `html` for `https://globed.eu/sitemap_index.xml` is a browser-viewer wrapper,
not the document — the XML declaration turned into an HTML comment and the root wrapped in
`<html><body>`, 1,610 bytes at `contentType: text/xml`. It does **not** fail to parse (the predicted
failure). It parses with root tag `html`, so `search._sitemap`'s index hop never fires and it returns
the child *sitemap files* as if they were content URLs; every one ends in `.xml`, the funding-path
filter drops them all, and `EntityExpansionSource` yields zero programme URLs per organisation while
reporting success. `sitemap_urls` therefore fetches through `egress.fetch_data_file` — origin bytes,
`ALLOWED_CONTENT_TYPES` already admits `application/xml` and `text/xml`. Unwrapping the vendor's
markup, or asking for `rawHtml`, is guessing at someone else's rendering pipeline. The cost: that
fetch is not behind `PacedFetch`'s per-domain lease, exactly as `registers.py`'s CSV downloads are
not.
`rawHtml` is the vendor's processed HTML, not origin bytes (measured: FAU 189,682 vs 422,515), and
the evidence chain says so. **Retention, robots and TDM reservations: the fetching vendor's
questions, owner decision 2026-09-18** — the earlier "read the retention terms before tier 3 stores
anything" gate is removed.

### 4.4 The cheap first read — measured before it decides anything

Our three-reading judge costs ~$0.35 per host; Firecrawl's JSON read costs 5 credits — $0.004 per
page on the Standard plan — and nobody has measured its precision on our schema. Reader plan Task 7, Step 4b: over the same
58 hosts, a `LineVerdict`-shaped schema with `quotes`, quotes checked mechanically against the
markdown, then side by side with the judge — served and agreed sets, precision on 30 hand-checked
awards, cost per host. Three outcomes, each recorded: **(a)** precision at or above the judge's → the
JSON read is the first pass and the judge runs only where a fact reaches a student or the two
disagree; **(b)** below → the JSON read is triage, deciding which pages the judge reads; **(c)**
poor → recorded, and the judge stays alone. ≈ 530 credits, inside the free tier.

### 4.5 Gate

The eight refused hosts of 2026-09-18 plus twenty from the next corridor sweep: recovered by
Firecrawl / by the Tavily fallback / `UNREACHABLE`, with cost. The three shell pages (Türkiye
Bursları, Sciences Po, JASSO) read to statements > 0. `changeTracking` returns `same` on an unchanged
re-read and the reader is not run. `europa.eu` never reaches a vendor (test). Plan: Standard
($83/month, 100,000 credits, 25 concurrent browsers) before the first corridor sweep; the free
1,000 credits carry the measurements.

## 5. C — the resolution queue

### 5.1 Shape

One model, `ResolutionItem` — a generalisation of `ConsultantResearchTask` (which has `url`,
`reason`, `state` and nothing to answer with). Fields: `kind` (the four below), `subject`
(organisation / award / host), `evidence` (names, candidate sites with titles, quotes, disputed
fields), `ask` (the one question, rendered), `options` (the buttons), `priority`, `expires_at`,
`resolved_by`, `resolution`, `state`. Listed on the **counsellor dashboard** (`/counselor/`, exists),
highest priority first. Frontend rendering is Aykhan's; this design specifies the behaviour and the
data.

### 5.2 The four items — ask, options, write-back

| kind | the counsellor sees | one click | written back, permanently |
|---|---|---|---|
| **SITE_UNKNOWN** | the organisation's name(s); the top 3 candidate sites with page titles | pick one · paste a URL · "not a funder" · "does not exist" | `Organisation.official_website`, `names += `, `status=REGISTERED`, `OrganisationIdentifier(source=HUMAN)`; "not a funder" → `kind=INFRASTRUCTURE`-class reject; the name is never asked again |
| **AWARD_DISPUTED** | the quoted sentences; **only the disputed fields**, each as a choice | "students apply — grant / waiver / loan / mixed" per field · "not an award" · "third party's money (pointer)" | `review_funding(accepted, note)` (exists on the reader branch: bound to the page's `sha256`, so it holds until the page changes); the chosen field values written to the row |
| **HOST_UNREACHABLE** | "we could not open X after 3 tries over 7 days" | paste the scholarship page URL · "closed / dead" | the URL is fetched and read; or `Organisation.status=REJECTED` with reason `UNREACHABLE` |
| **KIND_OR_COUNTRY_UNSURE** (once the classifier exists) | homepage title, the classifier's guess and confidence | foundation / ministry / company / university / not an organisation; country | `Organisation.kind`, `country_code`, marked human-verified |

Every ask is a *closed* question with the evidence attached; the counsellor never leaves the panel
to research. "I don't know" is always an option and parks the item for a second person.

### 5.3 Robustness ladder — what runs before anything is queued

In order, each removing volume from the next:

1. **A** — funder kinds and `HOLDER_OWN` (removes the pointer/unagreed class on funder pages).
2. **Third reading on `offered`** (3.3).
3. **Resolution with every name variant** the register or Wikidata supplies, kinds and place names
   from Wikidata per language, the six rules of 2026-09-17 §4.13b.
3a. **Diffbot Enhance on what is still unresolved** — measured 2026-09-18 at 7 of 10 on exactly the
   syllabic-acronym and Georgian-script names no lexical rule reaches
   (`research/2026-09-18-tool-capability-oversights.md`); confidence is low (0.16–0.54), so its answer
   takes the same title check; 400 free entities a month size it to the residue, never to bulk.
4. **The vendor fetch path and the retry queue** (B).
5. **Dedupe across tenants**: by registrable domain for organisations, by `canonical_key` for
   awards, by host for reachability — one resolution serves every agency.
6. **Priority**: items blocking a *current* student's pack first (the optimizer's no-floor signal
   names them); then registered hosts; then candidates; the rest expire after 30 days unopened.
7. **A daily cap per counsellor** (owner sets; default 20) so the queue is a task list, not a sink.

Target after the ladder: **under one host in ten per corridor reaches a person**, measured per
corridor in the tally and shown on the dashboard.

### 5.4 The trust catch — recorded for the owner to confirm

The catalog is shared by every agency, so a counsellor's answer becomes every tenant's truth.
Adopted default: **let it**, recording the resolving tenant and an `AuditEvent` on every
write-back; a second tenant's contrary resolution *reopens* the item rather than overwriting, and a
platform operator settles it (the `funding_review` command's role). Alternative, safer and slower:
every shared write waits for platform confirmation. Owner to confirm the default.

### 5.5 Gate

Thirty queued items worked by one counsellor with a stopwatch: median time per item < 60 s, zero
items needing research outside the panel, and every resolution provably absent from the next run's
queue (the same host or award not re-asked).

## 6. Data

- `FundingOpportunity` gains `holder` (choices in 3.1) and `eligibility_keys` (ArrayField); `scope`
  gains `HOLDER_OWN`; the reader's `FundingDecision` carries both. §3.5 adds `LineVerdict.applies_to`,
  `.stated_on`, `.deadline`; `FundingOpportunity.suspended_for`, `.suspension_quote`, `WITHDRAWN`;
  and `FundingCycleVerification` (one row per opportunity × intake: state, evidence, cadence, `cost_usd`).
- `ResolutionItem` (5.1), shared-catalog-adjacent but **tenant-scoped in listing** (a counsellor
  sees items that touch their students' packs plus a slice of the general backlog); resolutions
  write to shared tables through `catalog_ingestion`, with `resolved_by_tenant` and an
  `AuditEvent`. `ConsultantResearchTask` is migrated into it and retired.
- `OfficialSourceSnapshot` gains `fetched_via` (`FIRECRAWL / TAVILY_EXTRACT / SCRAPE_DO / EGRESS`,
  matching §4.3's label set as of the 2026-09-19 amendment)
  and `Organisation` gains `reachability` (`OK / RETRYING / UNREACHABLE`) with `next_retry_at`.
- `ResearchLead.found_via` gains `POINTER:<host>`.

## 7. Increments

1. **A on the reader branch** (owner's other session owns that worktree; this is a plan for it):
   holder literal, `HOLDER_OWN`, serve rule, pointers → leads, third reading on `offered`. Gate 3.4.
   Then §3.5 (reader plan Tasks 8–10): three fields on every verdict, negations join, withdrawal;
   the verification ladder and `FundingCycleVerification` with `cost_usd`; the truth set and the
   ≥ 95% gate. Steps 1–2 of the ladder wait on the Firecrawl client (increment 2).
2. **B — the vendor path. Done**, with one change from the plan as written: scrape.do (§4.1a)
   took the fallback-vendor role instead of Tavily Extract, per the owner decision recorded there
   on 2026-09-19. Built: the Firecrawl and scrape.do clients behind `fetch_page` in `egress.py`
   (final URL validated per vendor, `fetched_via` labelled), `changeTracking` gating the reader,
   the retry queue as a `reachability` state. `europa.eu` stays on our egress and a test asserts
   it. Not built in this pass, and not claimed here: `/crawl` replacing the link walker, the
   `maxAge` policy, and the retry queue's daily command — named in the self-review of the plan that
   executed this increment as deliberately separate work, because a crawl-traversal change alters
   what gets discovered, not how a page is fetched.
3. **Deletion plan** for the research path. **Done**, except two things kept on purpose, not
   missed: `LocalEgressProxy` survives — `apps/portals/engine.py` still imports it for the portal
   browser, and it leaves only with that tier's own glass-box deletion, a separate plan; and
   `readable_text`'s section selection (`_ADMISSION_TERMS`, `_selected`) survives because it is the
   local extractor the free-tier route in §4.1c depends on — deleting the one local extractor at
   the moment this system becomes vendor-dependent would remove the fallback exactly when it starts
   to matter. Deleted: the Scrapling ladder, `browser_server.py`, `BrowserTaskDefinition`,
   `BrowserSecurityGroup`, with the infra tests that pinned them updated in the same change, and
   `CLAUDE.md`'s Web-fetching section rewritten as record (this task). `/search` stays off.
4. **C**: `ResolutionItem` model and writers for the three live kinds; the `/counselor/` listing and
   the four write-backs; cross-tenant dedupe; priority and cap. Frontend by Aykhan against the
   behaviour here. Gate 5.5.
5. **C.4** when the classifier lands.
6. **D.1** schema 3 + consultation block + Art. 9 handling + erasure list.
7. **D.2** R5 affiliation lookup (resolver reuse; queue priority).
8. **D.3** the precision check and quote-beside-fact in the pack.
9. **D.5** field vocabulary CSV, ingestion read, profile read, candidate matching, cell phrasings.
10. **D.6** on-demand search: stage 1 (candidates behind the animation) then stage 2 (reader in
    background, pack versions bump); per-provider query allow-list and its test; per-tap budgets.
11. **D.5 per-institution route**: Exa `includeDomains` + `/contents subpages` — gate first (~$1).

## 7a. D — the student side of the bridge (final pass, 2026-09-18)

The sections above make discovery and reading as complete and honest as the measurements allow.
A *tailored* platform also needs the other end of the bridge to exist, and the final pass found
that it mostly does not: the profile cannot supply what the reader will write, the most personal
money cannot be swept for, nothing measures whether a served card is true, and the catalog has
**no field column** — a programme's discipline lives only in its name. D closes those.

### D.1 The consultation asks for every eligibility key — framed as scholarship eligibility

`StudentProfileSnapshot` (schema 2) holds nationality, country of residence, academic history,
experience, target field, languages, budget and preferences, and **none of** income/need, gender,
disability, refugee or displaced status, religion or community, sport or arts talent, professional
membership, or the *name* of an employer. Every eligibility key the reader will write is therefore
unfilterable today. Schema 3 adds them, and the consultation asks for them **as one block titled
"Scholarship eligibility"**, each question phrased as *"Some scholarships are reserved for … Does
this apply to you?"* with *prefer not to say* always available and never penalised: an unanswered
key means the pack neither includes nor excludes those awards — it shows them marked
*"eligibility not checked"*. Owner decision: ask; structure it for scholarships.

Special-category data (GDPR Art. 9): disability, religion or belief, and refugee/asylum status.
They are collected only under explicit, separate consent naming the purpose (matching scholarships
reserved for that group), stored as keys not narrative, excluded from every model prompt and every
provider query (the profile-free rule already forbids it), listed in the erasure field set, and
never shown to a counsellor except as the one word the student chose. `idea_v2.md`'s consultation
and the profile schema are amended together.

### D.2 R5 — affiliation lookup: the money only this student can get

Employer, bachelor's university (already in `academic_history`), home city or region, faith
community, professional body, bank. No sweep finds *this student's employer*; the consultation
asks, and the engine **looks those specific organisations up**: resolve each (register first —
Wikidata, ROR; search only by the organisation's public name, never a personal fact), read its
pages with the reader, attach awards with the matching key (`EMPLOYMENT`, `PRIOR_INSTITUTION`,
`RESIDENCE`, `AFFINITY`). A handful of hosts per student, high yield, and the organisation and its
awards land in the *shared* catalog (an employer's scholarship exists whoever asked) while the
student's link to it stays tenant-private. Its queue items (C) are **top priority** — they block a
real pack. Owner decision: add.

### D.3 Precision before any card is shown

Every gate so far counts served awards; none checks that a card's amount, deadline and
eligibility are true. Before the first pack: **30 served awards hand-checked against their pages**
(target ≥ 90% with no false eligibility), and the pack shows **the quoted sentence beside every
fact** so the student and the counsellor can see the source. Repeated on every 200 new served
awards. Owner decision: account for it.

### D.4 Reading budget per corridor — and the half of it that batching removes

Measured 2026-09-18: ~7 model calls and ~$0.35 per host, 10–15 minutes for a text-heavy page. A
2,000-host corridor is ~$700 per full read. So: read a page again **only when its content hash
changes** (the programme reader's cache already does this; the funding reader's
`funding_read_at`/snapshot path gets the same rule), and each corridor sweep states its reading
budget before it runs. Firecrawl's free `changeTracking` (git-diff) answers "did it change" without
a read. **Stage 2 of the on-demand search and the classifier run through the OpenAI Batch API or Flex
tier (50%, 24-hour window) and Anthropic Message Batches (50%), with prompt caching on both** (OpenAI
automatic at ≥ 1,024-token prefixes; Anthropic `cache_control`): the judge reads each chunk three
times, so the frozen instruction and the chunk go first and only the phrasing varies — the shared
prefix is the cache. Nothing in `apps/` uses either today
(`research/2026-09-18-tool-capability-oversights.md`).

### D.5 Field matching — Exa's embedding search does it at query time (owner correction 2026-09-18)

**State of the code:** `Program` has no discipline column; field lives in `name` and in
`ProgramStatement` text; the evaluator's `FIELD` constraint is a case-folded substring test. So
inside the catalog, "chemoinformatics" and "AI for chemistry" are strangers.

**Measured the same day, one call, $0.021:** the neural query *"a master's programme page in
chemoinformatics, computational chemistry, or data science applied to chemistry, at a European
university, that mentions a scholarship, stipend or tuition waiver for international students"*
returned 24 results: the ChEMoinformatics+ Erasmus Mundus master (its own grants page — "about 20
Erasmus Mundus scholarships" — and, dated 15/10/2025, a disclaimer that the 2026–2028 intake is
*without* scholarship: a discovery hit is a page to read, never a fact, and §3.5 is what reads it),
KU Leuven's Theoretical Chemistry and Computational Modelling
master's scholarships page, TU Braunschweig's *Artificial Intelligence for Molecular Sciences*,
Padua's *Complex and Data Driven Chemistry*, ITMO's *Infochemistry*, Aalto's and Uppsala's
programme pages, Utrecht's fee-support pages for two related programmes, and Stipendium
Hungaricum's bioinformatics listing. **The embedding did the neighbour expansion** — no vocabulary,
no synonym list — and it landed on programme-level pages that mention money, which is the hidden
gem the sweep otherwise reaches only by enumerating a university. The engine was underusing the
tool it already pays for.

**Design, corrected:**
- **Discovery-time semantics come from Exa neural search with a descriptive query** built from the
  student's target field and research interests, level, destination countries and the funding
  words — the shape measured best in the probe (describe the thing, no `category`, no
  `includeText`, `numResults: 100`). Brave runs the same intent as a keyword query for its
  independent index. This is the query the on-demand search (D.6) runs.
- **Exa `/contents` with `highlights` is used as transient triage**, exactly as §4.6 already
  permits: the one query-relevant sentence per result decides *which* pages the expensive reader
  reads ("about 20 Erasmus Mundus scholarships" → read; a fee table → read; a course list → skip).
  Nothing from it is stored; it cuts reader cost per tap by reading only pages that mention money.
- **Per-institution hidden gems:** for a registered university, one Exa call with
  `includeDomains=[its domain]` and the same descriptive query enumerates its programme and unit
  pages that mention funding, without a crawl. **Measured 2026-09-18, $0.022 each:** `tum.de` →
  the FIM Exclusive Scholarship, the Linde/MDSI Master's Scholarship and programme fee/aid pages;
  `metu.edu.tr` → three fully funded MSc positions at PETE, a departmental scholarship PDF, IPS and
  the ACHIEVE project. This is the **first pass over every registered HEI**; host inventory
  (crt.sh, `/map`) is the fallback for what it misses. `/contents` `subpages` followed off-host
  links on the test site, so it runs only behind our own on-host filter. `findSimilar` is live
  (the roster called it deprecated; $0.007) and gives "more like this programme" in one call.
- **The controlled vocabulary survives only as catalog tags** so a programme found once matches
  the *next* student without a new search: one cached read per programme at ingestion writes
  `buckets`/`tags` (ISCED-F detailed fields plus an interdisciplinary layer) with the quoted
  phrase; the profile gets the same tags. Matching in the catalog is tag overlap plus the existing
  fit dimensions; the substring test becomes one signal, never the gate. Gate: 50 programme
  names hand-mapped, ≥ 90% agreement.

### D.6 What happens when a student taps "search" — on-demand discovery, stored as it goes (owner decision 2026-09-18)

**The owner's correction:** the catalog is empty and the company is a startup, so the "catalog,
not live search" position is premature. **For now, tapping search runs the discovery engine
online for that student, an animation covers the wait, the finished pack is shown and everything
found is stored in the shared catalog.** The catalog grows with every search; the first student
in a cell pays the wait, later students in the same cell are served from what was stored, and the
design converges on catalog-first as it fills. Nothing above changes about *what* is discovered
or how it is verified — only *when*.

**The measured constraint that shapes it:** the funding reader costs 1–15 minutes and up to 36
model calls per host. A search that waits for every candidate to be *read* is 20–60 minutes, not
an animation. So the tap runs in **two stages**:

1. **Candidates, behind the animation (target ≤ 3 minutes).** Exa neural + Brave on the student's
   descriptive query (D.5); Tavily only for name→site resolution; registrable-domain dedupe against
   the register; `/contents` highlights as triage; the programme catalog rows written; the pack
   assembled from candidates **with provenance and a "reading in progress" state on funding**.
   Budget per tap: ≤ 40 provider calls, ≤ 30 pages fetched, no reader calls yet.
2. **Awards, in the background (minutes to an hour).** The reader serves awards page by page in
   the order triage ranked them; each served award bumps the pack version; the student is notified
   when the pack is complete or when the reading budget (≤ 60 pages, ≤ $15 per tap, settings) is
   spent. The R5 affiliation lookups run in this stage at top priority.
   > **Superseded 2026-09-23 — and not only the numbers.** The budget is no longer per tap at all:
   > **$50 is one student's search budget for a whole admission cycle**, a depleting wallet keyed
   > `(student, intended_intake)`, with the page cap demoted to a derived runaway backstop. The
   > "for now, search anyway" framing above is
   > replaced by a rule that converges without a switch (registrable-domain dedupe before any fetch;
   > read only what is new or changed). Live text:
   > `2026-09-22-funding-search-engine-master-design.md` §10.5. Everything else in D.6 — the two
   > stages, the per-provider query allow-list, storing as it goes — stands unchanged.

Everything is written to the shared catalog as it is verified — organisations, programmes,
snapshots, awards — under the same provenance rules as a background sweep, so a search *is* a
sweep, aimed by one student and paid for once.

**What a per-student query may carry.** Tavily's §9.2 perpetual licence over query text is why the
2026-09-17 design forbade profile fields in queries; Exa and Brave hold no such term, and the
owner's written permissions carry one condition (no competing-search training). Rule, per
provider: **Tavily stays profile-free** (name resolution only). **Exa and Brave queries may carry
non-identifying academic attributes** — target field and interests, level, teaching languages,
destination countries, and nationality *as a cell attribute* ("scholarships for Azerbaijani
students") — and **never** a name, an employer's or school's name together with the field, or any
Art. 9 key. Eligibility-key phrasings (women in engineering, refugees, disability) run only as
*cell-level* sweeps whose results are shared and cached, never as a query tied to one student's
tap. A test asserts the per-provider allow-list, replacing the blanket profile-free assertion.

**Rate and cost:** the existing pack-command limiter (20/min per student) plus a per-student
budget of two full searches a day and a per-tenant daily ceiling; every tap logs its provider and
model spend against its pack version.

**Still true, stated so nobody assumes otherwise:** the candidate-pool assembly from `Program`
rows and the optimizer are unbuilt; this section is what they are built *for*, and increment 10
below is where they land.

## 8. Alternatives considered

- **Widen the existing `POINTER` to be served when the host is a funder.** Serves the right pages
  but records no holder and keeps third-party pointers and own awards indistinguishable; the holder
  axis is the same work with a usable record.
- **Scrapling first, vendors later.** Cheaper per page and already built, but it spends our one
  egress address's reputation on the sites most likely to retaliate, and it needs the browser task
  running. Vendor-first costs credits and buys isolation.
- **Platform operators resolve everything.** Correct for trust, and it makes the queue a bottleneck
  on one team; the counsellor already knows the student the item blocks. Chosen: counsellor
  resolves, platform arbitrates disagreement.
- **A browser agent as the fetch tier.** Right tool for acting, wrong for reading.

## 9. Open items

- Firecrawl's retention terms for scraped content (blocks storing tier-3 output).
- Tavily extract `chunks_per_source` returned no chunks in two calls — confirm the shape before triage relies on it.
- Whether `HOLDER_OWN` needs the classifier's `kind` to be reliable on unregistered hosts, or the
  page title suffices (measured in gate 3.4).
- The owner's confirmation of 5.4.
- The owner's confirmation of the two-stage search (candidates in ≤ 3 minutes, awards filling in),
  which is the one place this design does not wait for the *final* pack behind the animation.
- Exa `subpages` needs an on-host filter before it is relied on; `includeDomains` is measured and adopted.
- The Azerbaijani and Uzbek resolution samples before those corridors are swept (carried from
  2026-09-17 §13).
