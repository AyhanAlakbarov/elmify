# Deep research prompt — where a new opportunity surfaces first

**Status:** ready to run. Written 2026-08-29. Run twice, independently, so the results can be
adjudicated.

**Why this exists.** Every other supplier in this system walks an index. An index-walker is
structurally blind to anything not in an index — including a scholarship announced last week. Two
questions we had been treating separately turn out to be the same one seen from opposite ends:

- *"If a good opportunity appears that nothing indexes, how do we spot it?"*
- *"Should we harvest per-country opportunity aggregators like `edumap.az`?"*

Both ask **how something reaches us that no index contains.** This run answers that empirically
rather than by architecture guesswork, and it produces the concrete input list a tip-off adapter
would need.

**This is a research run about *surfaces and cadence*, not about schemes.** Do not spend effort
cataloguing individual scholarships; other prompts do that. The deliverable is a map of where new
things appear, how fast, and whether a machine can watch them.

---

## Prompt

### Part A — enumerate the opportunity aggregators, per country

For each country below, identify the sites that **publish scholarship and study-abroad opportunities
to that country's own citizens** — the local, origin-side aggregators, of which `edumap.az`
(Azerbaijan) is the known example.

**Phase 1 — cover these properly before anything else:** **Azerbaijan, Türkiye.** These are the
launch markets; a thin answer here is worse than no answer for the rest.
**Phase 2:** Georgia, Armenia, Kazakhstan, Uzbekistan, Kyrgyzstan, India, Pakistan, Vietnam,
Indonesia.
**Only if capacity remains:** Serbia, Egypt, Jordan, Morocco, Nigeria, Kenya.

| Column | Notes |
|---|---|
| Site | Name and URL |
| Country and language | |
| Operator | Government, university, NGO, commercial, or individual |
| Coverage | Which funding families it posts — government inbound, outbound, bloc schemes, corporate, institution-local |
| Posting volume | Roughly how many opportunity posts per month |
| **Does a post link to the official source?** | **Decisive.** A post that links to the embassy or ministry page is usable as a tip-off; a post that only paraphrases is not |
| Structure | Whether posts are consistently formatted, tagged or categorised |
| Machine-readable route | RSS/Atom, JSON, API, sitemap with `lastmod`, or none |
| Stated terms | Whether the site publishes reuse or access terms, and what they say |
| Still active | Date of the most recent post you can see |

**Also cover the non-web channels**, which matter disproportionately in these countries: **Telegram
channels, mailing lists, Facebook groups and pages** that function as opportunity feeds. State
subscriber counts where visible, and whether any offers a machine-readable route.

### Part B — where a scheme is published *first*

Take a set of scholarship schemes whose announcement date you can establish, and trace where each
appeared earliest. Cover at least: a national inbound scheme, a bloc scheme, an embassy-announced
bilateral scheme, and an institution-local award.

For each, establish the **publication order** across these surfaces:

- the funder's own website
- the funder's or embassy's **social account**
- a ministry or agency **news/press page**
- a national aggregator
- a destination-country study-in-X portal
- any newsletter or mailing list

**The question is which surface is earliest and by how much**, not which is most authoritative. A
surface that carries the news three weeks before the official website is worth watching even if it
can never be cited.

### Part C — machine-readable watch routes

For every surface named in Parts A and B, establish whether it can be watched automatically:

- **RSS or Atom feed** — give the URL, and confirm it is live rather than a dead link in the page head
- **Sitemap with meaningful `lastmod`** — and whether `lastmod` actually changes when content does,
  since many CMSs emit a build timestamp instead
- **JSON endpoint behind the page** — the pattern that made Finland's registry usable
- **A news or announcements index page** that is stable and paginated
- **Email or Telegram subscription** — machine-readable only in the loosest sense, but a real channel

Report per surface, and be concrete: a URL that returns a feed, or a statement that none exists.

### Part D — latency and window, and why they decide the design

Two numbers govern how often anything must be swept, and they are the most useful output of this run:

1. **Announcement-to-deadline window.** From first public announcement to application deadline, for
   the schemes traced in Part B. Give the range and typical value.
2. **Announcement-to-indexing lag.** How long until the scheme appears somewhere stable and
   enumerable — the funder's own site, a portal, a registry.

State these plainly. **If schemes typically carry a three-week window, a monthly sweep misses most
of them and the design has to change**; if the typical window is four months, a slow cadence is fine
and the whole watch problem is smaller than assumed. Say which world we are in, with evidence.

Note explicitly any family whose windows are systematically short — bloc schemes and
embassy-announced bilateral schemes are the suspected cases.

### Part E — prior art

Does anything already do this? Look for scholarship alert services, aggregator APIs, government
notification services, and any open dataset of scholarship announcements. For each: coverage, terms,
cost, and whether it is a real index or an SEO content farm recycling dead schemes.

If a usable service exists, that is the most valuable finding in this run and should lead the
deliverable.

### Sourcing rules

1. **Verify every feed and endpoint you report by describing what it actually returns.** A `<link
   rel="alternate" type="application/rss+xml">` in a page head is not evidence the feed works; many
   are dead. This part of the run must be empirical.
2. **Date every observation.** Posting volumes and site activity change.
3. **Where a surface has no machine-readable route, say so plainly.** That is a finding, and it
   determines whether a human channel is the only option for that country.
4. **Distinguish an aggregator that links to sources from one that paraphrases them.** The first is
   usable; the second cannot be verified and is close to worthless to us.
5. Do not treat a site's age or design as evidence of quality. Some of the most current opportunity
   feeds in these countries are plain-HTML sites or Telegram channels.
6. **Flag any site that republishes dead or expired schemes without dating them** — that is the
   dominant failure mode in this category, and a site that does it cannot be trusted as a tip-off.

### What would change our plans

Flag explicitly: any origin-side aggregator with a working RSS/Atom feed or JSON endpoint **and**
posts that link to official sources — that is the ideal tip-off supplier and would move this from a
human channel to an adapter; any existing service that already aggregates announcements under usable
terms; a typical announcement-to-deadline window under one month, which forces a fast sweep cadence;
and any country where **no** watchable surface exists at all, which means a human is the only route
there and should be resourced as such.
