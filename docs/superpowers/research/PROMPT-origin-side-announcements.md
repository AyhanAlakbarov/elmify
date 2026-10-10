# Deep research prompt — the origin side: what a state announces to its own citizens

**Status:** ready to run. Written 2026-08-29. Run twice, independently, so the results can be
adjudicated.

**Scope note.** This is the **origin** side, and it is the third direction — not inbound
(`PROMPT-government-inbound-sweep.md`, what a country offers foreigners) and not the deep outbound
study of the two launch markets (`PROMPT-government-outbound-launch.md`, Azerbaijan's and Türkiye's
own state programmes). This run asks a different question from either: **what does a government tell
its own citizens is available to them, whoever pays for it.** Much of what it announces is somebody
else's money.

**Why this exists.** The gap-fill run's Task 1c was the axis meant to find schemes *by what actually
reaches students* rather than by organisational taxonomy. Across nine countries it produced two
bullets. That is the thinnest coverage of any axis in the programme, and it is the axis with no
substitute: a **bilateral country-pair agreement appears in no membership list and on no destination
page.** It surfaces only where a ministry announces it at home.

The cost of the gap is already visible. **Azerbaijan's Intergovernmental Scholarship Programme is a
live outbound state instrument that we know only from a news report** quoting application counts —
616 applications, 162 for China, 454 for Hungary, 457 of them for master's degrees. We have never
seen its own page, its eligibility, its route or its deadline. Georgia's International Education
Center and Armenia's Ministry of Education were both named by a prior run as the bodies that
"transform open international applications into state-managed diplomatic quotas", and no scheme was
extracted from either.

---

## Prompt

For each country below, establish **what its own government publishes to its citizens about funding
a master's degree abroad** — schemes it runs, schemes it nominates for, and schemes it merely
publicises.

### Countries

**In depth:** Azerbaijan, Türkiye.
**Then:** Georgia, Armenia, Kazakhstan, Uzbekistan.
**Then, as budget allows:** Kyrgyzstan, Tajikistan, Turkmenistan.

For Azerbaijan and Türkiye, their **own** state outbound programmes (the Azerbaijani state programme,
YLSY) belong to `PROMPT-government-outbound-launch.md`. Note each in one line and do not develop it —
but **do** cover, in full, what those two states announce about *foreign* funding, which that prompt
does not touch.

### This run is in local languages, and that is the point

An announcement page is rarely translated, and the English side of a ministry site is typically a
stale subset of the local-language one. Search and read in **Azerbaijani, Turkish, Georgian,
Armenian, Russian, Kazakh, Uzbek, Kyrgyz and Tajik**. Record which language each source was in, and
quote the operative sentence in the original with a translation.

**A run conducted entirely in English has not done this task.** Say so plainly if language access
forced a fallback for a given country, rather than reporting the English subset as the whole.

### Deliverable

**Part A — the announcement surfaces, one row per body.**

| Column | Notes |
|---|---|
| Country | |
| Body | Ministry, state agency or foundation, in its own language and in English |
| Announcement URL | The page where scholarship opportunities actually appear — not the homepage |
| Language(s) | And whether an English version exists and whether it lags |
| Cadence | Roughly how often something new appears, evidenced from dated posts |
| Archive | Whether past announcements remain reachable, and how far back |
| Machine-readable | RSS, JSON, a mailing list, or nothing |
| Access | Whether the page needs a browser, blocks plain fetches, or is served flat |

This part deliberately overlaps `PROMPT-new-opportunity-surfaces.md` Part A. That run asks about
**independent aggregators** like `edumap.az`; this one asks about **the state's own channel**. Where
both cover a body, say so — agreement across two runs on a surface worth watching is a result, not
a duplicate.

**Part B — the schemes found, one row per scheme.**

| Column | Notes |
|---|---|
| Scheme name | In its own language and in English |
| Announcing body | The origin-state body that published it |
| Funder | **Who actually pays — frequently a foreign state, bloc or university, not the announcer** |
| **Origin-state role** | `RUNS` / `NOMINATES` / `SELECTS` / `PUBLICISES ONLY`. Quote the sentence |
| **Application route** | `DIRECT` / `NOMINATED` / `HYBRID` — as it applies *to a citizen of this country* |
| Eligible nationalities | Verbatim |
| Destination(s) | |
| Degree level | Master's specifically |
| What it covers | |
| Quota | Any number published, with its year |
| Annual cycle | Opening and closing dates as announced locally |
| Official URL | The announcing body's page, and the funder's page where both exist |
| Source language | |

**The `Origin-state role` column is why this run exists.** A scheme the funder describes as open to
all can be, in practice, a scheme a citizen of one country can only enter through their own
ministry. **When the origin state nominates or pre-selects, the scheme is `NOMINATED` for that
nationality whatever the funder's own page says** — and a portfolio that lists it as a safety on the
strength of the funder's page is wrong for exactly the students we serve. Where the two sources
disagree, report both and say which governs.

**Part C — bilateral agreements specifically.** Treaty, protocol or memorandum name; the two parties;
whether it produces an annual quota and how large; who administers it on each side; where it is
announced; whether an application route is published at all.

**A bilateral that yields places but publishes no application page is still a finding.** Record it as
such. It tells a counsellor the route exists and must be entered through the ministry — which is
actionable, and invisible everywhere else.

**Part D — the sending-partner asymmetry.** Where the origin state acts as sending partner or
nominator for a foreign scheme, establish **what it publishes that the funder does not.** Hungary
publishes no per-country Stipendium Hungaricum quota; a sending partner may publish its own number.
Prior synthesis established that *who publishes the quota* is itself the finding; this part tests how
far that generalises.

**Part E — confirmed silence.** Countries whose government publishes no such channel, or whose
channel is dead, with the page and date that establishes it. For Turkmenistan in particular, an
evidenced "nothing is published" is a genuine result and should not be padded.

### Known starting points — a floor, not the scope

Derive the body list per country; these are where prior runs stopped, not where this one should.

- **Azerbaijan** — State Agency for Science and Higher Education (**find the Intergovernmental
  Scholarship Programme's own page**; the news report is a lead, not a source), Ministry of Science
  and Education.
- **Türkiye** — YTB, Ministry of National Education, Directorate for EU Affairs (Jean Monnet was
  found through this channel and nothing else).
- **Georgia** — International Education Center.
- **Armenia** — Ministry of Education, Science, Culture and Sport.
- **Kazakhstan** — Center for International Programs, Ministry of Science and Higher Education.
- **Uzbekistan** — El-Yurt Umidi Foundation, Ministry of Higher Education.
- **Kyrgyzstan, Tajikistan, Turkmenistan** — the education ministry, and the foreign ministry where
  bilateral quotas are announced diplomatically rather than educationally.

### Sourcing rules

1. **A news report is a lead, never a source.** Chase every one to the announcing body's own page. If
   the page cannot be found, say the claim rests on a news report and name it — do not launder it.
2. **Quote the operative sentence in the original language with a translation**, for eligibility,
   route and deadline.
3. **Date every announcement**, and give the cycle it belongs to. These pages are frequently left up
   years after the scheme closed.
4. **Distinguish "announced once" from "runs annually."** A single 2023 post is not evidence of a
   live programme; say which you found.
5. **Where a page is JS-loaded, gone, or blocks retrieval, record the URL and the failure.** That is
   an input to our own fetching design, not a dead end to hide.
6. Where the origin-side and funder-side accounts conflict, give both with dates.

### What would change our plans

Flag explicitly: **any scheme where the origin state's role converts a `DIRECT` scheme into a
`NOMINATED` one** for our students, since that invalidates a floor we might otherwise build on; any
bilateral quota not visible from the destination side; any origin-state channel with a feed or a
stable archive, which would be a supplier rather than a research finding; any live outbound state
programme in Georgia, Armenia, Kazakhstan, Uzbekistan, Kyrgyzstan or Tajikistan that no prior run has
named; and any country where the announcement channel is a messaging platform rather than a website,
which would defeat every fetching design we have.
