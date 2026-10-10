# Deep research prompt — government inbound scholarship sweep

**Status:** ready to run. Written 2026-08-29. Run twice, independently, so the results can be
adjudicated against each other.

**Scope note.** This is the broad half of a split: **inbound schemes only**, across ~50 countries,
at survey depth. The **outbound** provision of the two launch markets is a separate run at maximum
depth (`PROMPT-government-outbound-launch.md`). Do not cover outbound schemes here — the two
directions want opposite scopes, and answering both in one pass produces a thin version of each.

**Why this exists.** We hold a handful of destination-inbound schemes (DAAD, GKS, CSC, Türkiye
Bursları, Stipendium Hungaricum) and nothing systematic. A government instrument is a
**country-level object** — this feeds the instrument sweep and `DestinationPolicy`, not programme
discovery.

**Note on splitting further.** ~50 countries is still a lot. If a single run cannot cover them at
adequate depth, **split by region and run each separately** rather than thinning the per-country
answer. A shallow row for fifty countries is worth less than a solid row for fifteen.

---

## Prompt

For each country listed below, establish **what master's-level scholarships its government offers to
foreign nationals to study in that country** — the INBOUND direction only.

Schemes by which a country funds *its own citizens* to study abroad are out of scope here.

### Countries

**EU 27:** Austria, Belgium, Bulgaria, Croatia, Cyprus, Czechia, Denmark, Estonia, Finland, France,
Germany, Greece, Hungary, Ireland, Italy, Latvia, Lithuania, Luxembourg, Malta, Netherlands, Poland,
Portugal, Romania, Slovakia, Slovenia, Spain, Sweden.

**Also:** United Kingdom, Northern Ireland, United States, Iceland, Canada, Australia, New Zealand,
Japan, South Korea, China, Hong Kong, Singapore, Brunei, India, Russia, Kazakhstan, Azerbaijan,
Georgia, Armenia, Türkiye, Serbia, United Arab Emirates, Qatar, Kuwait, Bahrain, Israel.

**Also, as regional destinations our students realistically consider:** Pakistan, Vietnam, Indonesia,
Uzbekistan, Malaysia.

**If capacity forces a cut, cut the countries our students are least likely to go to**, and say
which you cut. A country dropped and named is a gap we can fill later; a country covered in one
under-sourced line is a gap we will not notice.

### In a federal or devolved state, "the government" is not one funder

The country list below is a list of *states*, and that framing has a known blind spot: **sub-national
governments run their own schemes and no run in this programme has ever looked at one.** Bavaria
funds international students at Bavarian state universities through the Bavarian State Ministry of
Science and the Arts, and BAYHOST — the Bavarian Academic Centre for Central, Eastern and
Southeastern Europe — funds graduate students from a named list of ten countries. That second one is
sub-national **and** nationality-keyed, which is why neither this prompt nor the nationality-keyed
run would have reached it.

BAYHOST's own list does not include any of our nine countries. **It is cited as proof the tier
exists, not as a hit** — the point is that an entire class of funder has never been in frame.

**For every federal or devolved state on the list** — Germany, Spain, Italy, Switzerland, Canada,
Belgium, Austria, and any other where education is a regional competence — establish whether the
regions, Länder, autonomous communities, cantons or provinces run their own international master's
scholarships, and cover the ones that do as separate schemes with their own rows. **Where the
national scheme is the only one, say so explicitly.**

If this doubles the work for one country, it is a country worth splitting into its own run rather
than thinning.

### Tracks inside a scheme

**A scheme is a set of tracks, and they are not all keyed the same way.** Treat "what does country X
offer" as answered only once you have established whether the scheme fans out into sub-programmes
with their **own quota table, own eligible-country list and own eligibility key**.

The keys to look for, because each is invisible to a search built around the others:

- **Descent / heritage / co-ethnic** — eligibility by ancestry rather than citizenship. Terms to
  search in the scheme's own language: *overseas*, *diaspora*, *heritage*, *compatriot*,
  *соотечественник*, *akraba topluluklar*, *日系*, *재외동포*.
- **Region or bloc** — eligibility naming a region rather than a state ("South Caucasus", "Silk
  Road", "Pacific"), which can be an application entity in its own right rather than a label.
- **Bilateral / government-to-government** — a track entered through an embassy or a home ministry
  rather than the scheme's open portal, usually with its own quota.
- **Religious, linguistic or historical affinity** — OIC, Francophonie, Lusophone and equivalents.

**This is not hypothetical, and it is why this section exists.** The Global Korea Scholarship
publishes, in the same NIIED guideline as its embassy quotas, an **Overseas Korean/Adoptee track of
24 places across 8 countries — 16 of them in Kazakhstan, Kyrgyzstan and Uzbekistan.** It is keyed to
Korean descent, not citizenship, so for a Kazakh applicant of Korean descent it changes the pool
from 13 places contested by 143 countries to a second route contested by 8. Two prior research runs
covered GKS and neither surfaced it, because both tested eligibility against the applicant's
*nationality* and a descent track never names a nationality. Chevening's "South Caucasus" entity was
missed the same way. Evidence:
`docs/superpowers/research/2026-08-29-gks-quota-primary-verification.md` §4.

**Two specific suspects, to be checked rather than assumed:**

- **Russia** — the Rossotrudnichestvo quota is the most likely place in this whole sweep to carry a
  *соотечественник* (compatriot) track. Establish whether the quota is one pool or several, and
  whether compatriot status is a separate route with its own allocation.
- **Japan (MEXT)** — check for a *nikkei* / Japanese-descent route alongside the Embassy and
  University Recommendation tracks.

**Where a scheme has exactly one track, say so explicitly.** "Checked for sub-tracks, found one
general track" is a result; silence is indistinguishable from not having looked.

### Deliverable

**Part A — one row per _track_, not per scheme.** A scheme with three differently-keyed tracks
is three rows.

| Column | Notes |
|---|---|
| Country | |
| Scheme name | Official, and in its own language where that differs |
| Track | The named sub-programme this row describes, or `general` if the scheme has only one |
| **Eligibility key** | What eligibility is keyed to: `CITIZENSHIP` / `DESCENT` / `REGION` / `RESIDENCE` / `OPEN`. Quote the clause |
| Administering body | Ministry, agency or foundation |
| Degree level | Confirm master's specifically; exclude doctoral-only and undergraduate-only |
| **Application route** | **`DIRECT` / `NOMINATED` / `HYBRID`** — quote the sentence establishing it |
| Eligible nationalities | Any restriction, quota table, or partner-country list. Reproduce the rows for **Azerbaijan and Türkiye** wherever a quota table exists — these are the launch markets — then Georgia, Armenia, Kazakhstan, India, Pakistan, Vietnam and Indonesia |
| What it covers | Tuition / stipend / travel / insurance / accommodation |
| Post-award obligation | Any requirement to leave, stay, or work in the country after graduating, and any repayment clause. Quote it |
| Annual cycle | Opening and closing dates |
| Official URL | The scheme's own page |
| Numbers published | Awards, applicants, or neither. **Do not compute a rate unless both halves are published** |
| Terms for automated retrieval | Whether the site states reuse or access terms |

**Part B — countries with no inbound scheme.** A confirmed absence is a finding. State which
countries run no government inbound master's scholarship at all, with the basis for saying so.

**Part C — where these are indexed, if anywhere.** For each scheme: does it appear in any aggregate
directory or machine-readable feed, or only on its own site? **If any cross-country index of
government scholarships exists anywhere, that is the most valuable single finding in this run** — no
such index has been located to date. Name it, give its coverage and terms.

### Sourcing rules

1. **Primary sources only for load-bearing claims** — the ministry, the agency, the official gazette.
   Study-abroad blogs may help you *find* a scheme; never use one to establish a fact about it.
2. **Quote the operative sentence** for eligibility, application route, degree level and any return
   obligation.
3. **Date every fact.** Schemes change annually. A 2021 quota is not a current one and must be
   labelled with its year.
4. **Say when something is unpublished.** "No applicant count is published" is a result. Do not fill
   a gap with a weaker source, and do not infer a number from a related one.
5. **Do not present a scheme as live without a current-cycle source.** Several national programmes
   have been quietly suspended; report status explicitly rather than assuming continuity.
6. Where sources conflict, give both with dates and let the reader adjudicate.
7. **Keep inbound and outbound strictly apart.** A prior sweep conflated a country's inbound scheme
   with its outbound one, which produced a materially wrong model. If you encounter an outbound
   programme, note its existence in one line and move on — it belongs to the other run.

### What would change our plans

Flag explicitly: any cross-country index of government scholarships; any scheme that is `DIRECT`
and full-cost for **Azerbaijani or Turkish citizens** — the launch markets — and then for Georgian,
Armenian, Kazakh, Indian, Pakistani, Vietnamese or Indonesian ones; any scheme with a
machine-readable feed; **any descent-, compatriot- or region-keyed track inside a scheme we already hold**, since that is a route our catalog cannot currently represent at all; any scheme suspended or closed since 2024; and any destination whose inbound
scheme is open to our launch markets but excluded from the post-study work route, which would look
like a floor and is not.